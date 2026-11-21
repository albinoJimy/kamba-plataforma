"""O CHR (TypeScript) contra o PostgreSQL do gate — KAM-014.

O codigo vive em `packages/core-ts/src/chr/` e os seus testes de base de dados
em `packages/core-ts/tests_bd/chr.bd.test.ts`. Esta suite e o que os poe a
correr contra a base descartavel, com os **tres papeis verdadeiros** —
`kamba_resolver`, `kamba_identity` e `kamba_app` — e as migracoes em `head`, e e
ela que le o que eles deixam: a saida, os numeros que eles medem e a cobertura
de `src/chr/`.

Porque e suite propria, e nao mais um ficheiro em `tests`: e **TypeScript**
contra a base, como a de identidade e a de eventos, e nenhuma das baterias de
`db/tests/` corre Node. E porque a resposta a pergunta do CHR depende do papel
da ligacao — `kamba_app` sem contexto ve zero linhas e `kamba_resolver` ve
todas —, o que obriga a abrir ligacoes com papeis que `db/tests/` nao usa.

**O que esta suite nao mede**, e onde se mede: a decisao (que caminho cada
evento segue, a matriz celula a celula, a forma do *job*) vive nas baterias do
gate 4, em `packages/core-ts/tests/chr.*.test.ts` — uma base falsa devolve o que
se lhe mandou devolver, e um teste de isolamento sobre ela nao prova isolamento
nenhum. O que so aqui se prova esta na docstring do ficheiro TypeScript.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.base import ComBase
from tests_chr import node

sys.path.insert(0, str(node.RAIZ / "tools"))

from kamba_yaml import load_file  # noqa: E402

#: Os ficheiros de teste, pela ordem em que correm. Os de cima nao precisam de
#: base (correm tambem no gate 4) e estao aqui pela cobertura: sem eles, a
#: medida de `src/chr/` nao incluiria o que eles exercitam, e o limiar do
#: estrato `critico` nao se podia aplicar por ficheiro.
FICHEIROS = (
    "tests/chr.canal.test.ts",
    "tests/chr.conversas.test.ts",
    "tests/chr.fluxo_b.test.ts",
    "tests/chr.invocacao.test.ts",
    "tests/chr.metricas.test.ts",
    "tests/chr.test.ts",
    # KAM-211: o `reply.id` do botao ate ao `agent_invocation`, e a troca de
    # telefone do dono pela `definir_dono` como `kamba_identity`.
    "tests/chr.botao.test.ts",
    "tests_bd/chr.bd.test.ts",
    "tests_bd/dono.bd.test.ts",
    # KAM-215: o dono nasce do provisionamento — o caso avanca pela porta como
    # `kamba_batch`, e o `tenant.provisioned` consome-se como `kamba_app` com o
    # contacto e a porta como `kamba_identity`.
    "tests_bd/provisionamento.bd.test.ts",
)

#: Os grupos de `tests_bd/chr.bd.test.ts`: um por propriedade que **so** se
#: prova contra a base. Se um desaparecer, a suite deixa de provar essa
#: propriedade — e isso tem de falhar aqui, nao passar por haver menos testes.
GRUPOS = (
    "critério 8 — isolamento: o phone_number_id de A nunca devolve B",
    "critério 4 — BSUID e telefone convergem no mesmo contact_id",
    "o gancho de fusão reaponta conversas, e a colisão dobra os tempos",
    "DoD — idempotência: o mesmo wamid não cria duas conversas nem dois jobs",
    "critério 2 — quarentena de um phone_number_id desconhecido",
    "critério 5 — a guarda do ADR-011 no arranque",
    "critério 3 — a matriz de estados contra a base",
    "critério 7 — uma conversa que não está em `bot` não vai ao AGR",
    "critério 8 — latência de `resolve`",
    "privacidade — nada do interlocutor chega ao job nem à conversa",
    "KAM-092 — o tenant.activated esquece o tenant na cache do CHR",
    # KAM-098: a suspensao (o criterio 2 do KAM-058) e o encerramento.
    "KAM-058 e KAM-098 — a suspensão e o encerramento esquecem o tenant na cache do CHR",
    # KAM-211 e KAM-217: a porta do dono pelo caminho real, e a troca montada
    # como o `onboarding-web` a monta, sobre o pool. Revisto no KAM-223: a troca
    # com prova de posse (regra C) tem grupo proprio, e a porta fica no seu.
    "KAM-211/217 — a porta do dono, contra a base",
    "KAM-223 — a troca com prova de posse, contra a base",
    # KAM-223: a conversa do dono pelo painel, com a fonte persistida.
    "KAM-223 — a conversa do dono pelo painel, contra a base",
    # KAM-216: o canal do dono guardado pela troca e lido pelo painel.
    "KAM-216 — o canal do dono guardado, contra a base",
    # KAM-215: o dono do provisionamento, a reentrega, o isolamento e os dois
    # adversariais do bloco.
    "KAM-215 — o dono nasce do provisionamento, contra a base",
    # KAM-232: o texto do WhatsApp na fonte persistida, a reentrega e o
    # isolamento.
    "KAM-232 — o texto do WhatsApp na `agent_messages`, contra a base",
)

#: Testes que **tem** de ter corrido e passado, pelo nome. Lista curta, com os
#: que dao a letra de cada criterio.
TESTES_OBRIGATORIOS = (
    "o resolvedor responde sem contexto, e cada pnid devolve o seu tenant",
    "`kamba_app` sem contexto **nao** consegue responder: zero linhas",
    "só wa_id e depois só BSUID: um contacto, e `contact.merged` uma vez em dez repetições",
    "sem colisão: a conversa do absorvido passa para quem fica",
    "com colisão no mesmo canal: dobra os tempos e não viola a UNIQUE",
    "se o gancho lançar, a fusão inteira é desfeita",
    "o mesmo evento duas vezes deixa uma conversa e dois jobs com o mesmo jobId",
    "uma linha, com o motivo `canal_desconhecido`, e a re-entrega não deixa outra",
    "com `kamba_app`, a guarda **recusa-se a correr** em vez de contar zero",
    # **Mudou de objecto com o KAM-018**, e a razao esta no proprio teste: a
    # revisao `0016` concede `UPDATE (mode, last_human_activity_at)` a
    # `kamba_app` — o privilegio que a `0009` deixou de fora a dizer «e esse
    # ticket que o pede» —, pelo que a afirmacao antiga passou a ser falsa. O
    # que este teste guarda agora sao as quatro colunas da identidade da
    # conversa, que nenhuma revisao concede.
    "`kamba_app` não consegue reescrever a identidade da conversa",
    "p95 de 40 resoluções: sem cache ≤ 50 ms, com cache ≤ 5 ms",
    "o BSUID e o telefone não aparecem no job, nem na linha de `conversations`",
    # KAM-092, criterio 7: a activacao emitida pelas portas da base, consumida
    # pelo `consumir` do KAM-006 com o efeito do CHR, esquece o tenant na cache.
    "a activação pelas portas chega ao consumidor do CHR, e a primeira mensagem seguinte chega ao AGR",
    # KAM-058, criterio 2, e KAM-098, criterio 3: o fim-a-fim com o `Chr` e um
    # AGR espiao, pelos envelopes que a regua e o encerramento emitem.
    "a suspensão pela régua (KAM-058, critério 2): chega ao consumidor do CHR, e a mensagem seguinte já não chega ao AGR espião",
    "o encerramento pelo off-boarding (KAM-098, critério 3): chega ao consumidor do CHR, e a mensagem seguinte já não chega ao AGR espião",
    # KAM-211: a troca pelo caminho real, e a porta fechada ao `kamba_app`.
    # Revisto no KAM-223: o codigo do numero novo ja nao move o papel (regra C);
    # o papel muda pelo codigo do numero antigo, ou passadas as 72 h.
    "o codigo do numero novo poe a troca pendente e NAO move o papel; passadas as 72 h, move",
    "com o codigo do numero antigo a troca e imediata",
    "o codigo certo de um numero que nao e o do dono desfaz a transaccao: papel e troca como estavam",
    # KAM-223: a conversa do dono, e o cursor de outro tenant.
    "a leitura mostra as mensagens do dono e so as respostas entregues; o cursor de B da nao_encontrado",
    "com o papel da aplicação, a porta não executa",
    # KAM-216: os dois cenarios do criterio 3, e o isolamento.
    "telefone diferente do número da loja: a troca guarda o WhatsApp, e o painel lê-o",
    "telefone igual ao número da loja: o dono que volta ao número do registo tem o painel",
    "isolamento: a troca de B não escreve o canal de A",
    # KAM-217: duas trocas concorrentes de dois tenants, cada uma no seu.
    "cinco pares de trocas concorrentes em dois tenants acabam cada uma no seu tenant",
    # KAM-215: os quatro criterios, o isolamento e os dois adversariais do bloco.
    "saga → tenant.provisioned → contacto dono; a reentrega 3× deixa 1 dono",
    "duas varreduras ao mesmo tempo dão um tenant.provisioned, e o caso chega uma vez",
    "isolamento: o evento de A com o tenant de B não cria dono em B nem em A",
    "adversarial: um onboarding_id de outro tenant no payload vai à DLQ e não cria dono",
    "adversarial: um phone_enc ilegível vai à DLQ e não cria dono",
    "adversarial: um phone_enc copiado de outro caso (de outro tenant) não decifra, e vai à DLQ",
    "um passo da saga com o onboarding_id deste caso e o tenant de outro não avança o caso",
    # KAM-232: a reentrega da uma linha, o isolamento e a linha imutavel.
    "a reentrega 3x grava uma linha, como `kamba_app`, e a invocacao leva o identificador dela",
    "duas mensagens sao duas linhas; o mesmo `wamid` noutro tenant e outra linha, invisivel a este",
    "o `kamba_app` continua sem `UPDATE` nem `DELETE` na linha que gravou",
)

#: Os ficheiros do modulo. A cobertura mede-se em **cada um**.
#:
#: O `fila.ts` **nao** esta aqui, e nao e esquecimento: e casca sobre o BullMQ
#: (uma `Queue` e um `add` com `jobId`), e quem o exercita de verdade e uma fila
#: real — que esta suite nao levanta, porque a porta do AGR e uma interface e o
#: que se faz com o *job* e KAM-025. Medi-lo aqui dava-lhe 0% para sempre. A
#: parte que pode errar em silencio — a forma do `jobId` — e o `invocacao.ts`, e
#: tem bateria propria no gate 4.
FICHEIROS_DO_MODULO = (
    "activacao.ts",
    "canal.ts",
    "chr.ts",
    "consultas.ts",
    "contrato.ts",
    "conversas.ts",
    "fluxo_b.ts",
    "invocacao.ts",
    "metricas.ts",
    "index.ts",
)


def _cobertura(lcov: str) -> dict[str, tuple[int, int]]:
    """ficheiro de `src/chr/` -> (linhas cobertas, linhas encontradas)."""
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
            if "/src/chr/" in f"/{actual}":
                medidas[actual.rsplit("/", 1)[-1]] = (cobertas, encontradas)
            actual = None
    return medidas


class TestModuloDoChr(ComBase):
    """Corre os testes em Node **uma vez**, e depois olha para o que ficou."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.saida = Path(tempfile.mkdtemp(prefix="kamba-chr-"))
        cls.execucao = node.correr(
            [
                "--test",
                # Um ficheiro de cada vez: a tabela de versoes de chave e
                # global, e os ensaios de arranque contam linhas de Fluxo B em
                # **toda** a base — dois ficheiros em paralelo veriam as linhas
                # um do outro.
                "--test-concurrency=1",
                "--experimental-test-coverage",
                "--test-reporter=tap",
                "--test-reporter-destination=stdout",
                "--test-reporter=lcov",
                "--test-reporter-destination={saida}",
                *FICHEIROS,
            ],
            cls.saida / "chr.lcov",
        )
        cls.tap = cls.execucao.stdout
        cls.escrito = cls.execucao.stdout + cls.execucao.stderr

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.saida, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def _falhas_do_tap(cls) -> str:
        """As linhas `not ok` e o que vem com cada uma, so.

        O relatorio de cobertura ocupa milhares de linhas no fim da saida, e um
        `escrito[-6000:]` na mensagem de falha mostrava **so** isso — o
        diagnostico ficava de fora. Medido: a primeira execucao desta suite
        falhou e a mensagem nao dizia porque. Esta funcao tira o que interessa.
        """
        linhas = cls.escrito.splitlines()
        partes: list[str] = []
        for indice, linha in enumerate(linhas):
            if re.match(r"^\s*not ok \d+ - ", linha):
                partes.append("\n".join(linhas[indice : indice + 30]))
        resumo = [l for l in linhas if re.match(r"^# (tests|pass|fail) \d+$", l)]
        return "\n\n".join([*partes, " | ".join(resumo)]) or cls.escrito[-4000:]

    def test_os_testes_do_chr_passam(self) -> None:
        """As falhas do TAP entram na mensagem: e o que se vai ler."""
        self.assertEqual(
            self.execucao.returncode,
            0,
            f"node --test saiu com {self.execucao.returncode}:\n"
            f"{self._falhas_do_tap()}",
        )

    def test_nenhum_teste_foi_saltado(self) -> None:
        """Num gate, saltar e falhar — a mesma regra do `correr_suite.py`."""
        saltados = re.findall(r"^# skip (\d+)$", self.tap, re.M)
        self.assertEqual(
            [int(n) for n in saltados] or [0], [0], f"TAP:\n{self.tap[-3000:]}"
        )

    def test_os_grupos_de_base_de_dados_correram_todos(self) -> None:
        """Um grupo que desapareca e uma propriedade que deixou de se provar."""
        for grupo in GRUPOS:
            with self.subTest(grupo=grupo):
                self.assertIn(grupo, self.tap)

    def test_os_testes_obrigatorios_passaram(self) -> None:
        """Pelo nome, e com `ok` a frente: a letra de cada criterio."""
        for nome in TESTES_OBRIGATORIOS:
            with self.subTest(teste=nome):
                self.assertRegex(self.tap, rf"(?m)^\s*ok \d+ - {re.escape(nome)}$")

    def test_a_medicao_de_latencia_saiu_no_registo(self) -> None:
        """O numero tem de aparecer **e tem de se poder ler** no registo do gate.

        O `console.log` do ensaio vai para o TAP, que esta suite captura e nao
        reimprime: sem este `print`, o numero existia e ninguem o via — e e ele
        que a seccao de verificacao do ticket cita. Imprime-se aqui, para o
        registo do gate, e nao se confia em ir procura-lo a uma saida capturada.
        """
        medidas = re.findall(r"\[KAM-014\][^\n]*", self.escrito)
        for linha in medidas:
            print(f"    {linha.strip()}")
        self.assertRegex(
            self.escrito,
            r"\[KAM-014\] p95 resolve: sem cache [0-9.]+ ms, com cache [0-9.]+ ms",
        )
        self.assertRegex(self.escrito, r"\[KAM-014\] invalidacao \+ releitura: [0-9.]+ ms")

    def test_a_cobertura_do_modulo_e_pelo_menos_a_do_estrato_critico(self) -> None:
        """O gate 4 nao tem base de dados; a cobertura de `src/chr/` mede-se aqui.

        O limiar e **lido** de `ci/thresholds.yaml`, do estrato `critico`, e nao
        escrito aqui: dois numeros em dois sitios divergem. O CHR entra nesse
        estrato porque e onde o `tenant_id` nasce — e `specs/01` §4.1 poe o
        isolamento de tenant la.
        """
        lcov = self.saida / "chr.lcov"
        self.assertTrue(lcov.is_file(), f"nao houve LCOV:\n{self.escrito[-3000:]}")
        medidas = _cobertura(lcov.read_text(encoding="utf-8"))
        limiares = load_file(node.RAIZ / "ci" / "thresholds.yaml")
        minimo = next(
            int(e["minimo_linhas"])
            for e in limiares["estratos"]
            if e["nome"] == "critico"
        )
        em_falta = [f for f in FICHEIROS_DO_MODULO if f not in medidas]
        self.assertEqual(em_falta, [], f"sem medida: {em_falta}; medidos: {sorted(medidas)}")
        for ficheiro in FICHEIROS_DO_MODULO:
            cobertas, encontradas = medidas[ficheiro]
            percentagem = 100 * cobertas / max(encontradas, 1)
            with self.subTest(ficheiro=ficheiro):
                self.assertGreaterEqual(
                    percentagem,
                    minimo,
                    f"{ficheiro}: {cobertas}/{encontradas} = {percentagem:.0f}%",
                )


if __name__ == "__main__":
    unittest.main()
