"""O handoff (TypeScript) contra o PostgreSQL do gate — KAM-019.

O codigo vive em `packages/core-ts/src/hnd/` e os seus testes de base de dados
em `packages/core-ts/tests_bd/handoff.bd.test.ts`. Esta suite e o que os poe a
correr contra a base descartavel, com as migracoes em `head`, e e ela que le o
que eles deixam: a saida, os numeros que eles medem e a cobertura de `src/hnd/`.

Porque e suite propria, e nao mais um ficheiro em `tests`: e **TypeScript**
contra a base, como a de identidade, a de eventos, a do CHR e a da saida, e
nenhuma das baterias de `db/tests/` corre Node.

**O que esta suite nao mede**, e onde se mede: a traducao entre os dois
vocabularios de estado, a autenticacao dos *callbacks*, a leitura do corpo, a
ordem dos passos e o cliente do Chatwoot vivem nas baterias do gate 4, em
`packages/core-ts/tests/hnd.*.test.ts` — sao funcoes puras e portas, e uma base
real nao acrescenta nada a prova. O que **so** aqui se prova esta na docstring
do ficheiro TypeScript, e e disso que os `GRUPOS` abaixo sao a lista.

**E o que nenhuma das duas mede**: se o token do *agent bot* consegue passar
`pending -> open` no Chatwoot a serio. E o L7, NAO VERIFICADO
(`docs/tecnica/01` §18), e o criterio 8 pede um spike com evidencia escrita —
`docs/evidencia/KAM-019-bot-open.md`. Nenhuma porta falsa responde a essa
pergunta, e e por isso que ela nao esta aqui.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.base import ComBase
from tests_handoff import node

sys.path.insert(0, str(node.RAIZ / "tools"))

from kamba_yaml import load_file  # noqa: E402

#: Os ficheiros de teste, pela ordem em que correm. Os de cima nao precisam de
#: base (correm tambem no gate 4) e estao aqui pela cobertura: sem eles, a
#: medida de `src/hnd/` nao incluiria o que eles exercitam, e o limiar nao se
#: podia aplicar por ficheiro.
FICHEIROS = (
    "tests/hnd.estados.test.ts",
    "tests/hnd.callbacks.test.ts",
    "tests/hnd.chatwoot.test.ts",
    "tests/hnd.provedor.test.ts",
    "tests/hnd.resposta.test.ts",
    # KAM-019, emenda 1.42: o cliente de `/internal/resume`. Entra nesta lista
    # **no mesmo diff** que o cria, e a razao esta escrita no comentario do
    # `FICHEIROS_DO_MODULO` abaixo: o `resposta.ts` ficou fora dela e a bateria
    # dele apodreceu em silencio, porque o glob `tests/hnd.*.test.ts` a corria e
    # o CI nao.
    "tests/hnd.retoma.test.ts",
    "tests_bd/handoff.bd.test.ts",
)

#: Os grupos que **tem** de aparecer na saida, um por propriedade que a suite
#: prova. Se um desaparecer, a suite deixa de provar essa propriedade — e isso
#: tem de falhar aqui, nao passar por haver menos testes.
#:
#: Os sete primeiros sao das baterias do gate 4 (funcoes puras e portas); os
#: quatro ultimos sao do ensaio de base e sao os que **so** um PostgreSQL prova.
GRUPOS = (
    "os dois vocabularios",
    "o segredo do bot",
    "a leitura do corpo",
    "o provisionamento (criterio 1 e 2)",
    "o setBotMuted levanta (criterio 8)",
    "o que o spike e a revisao fecharam",
    "o fecho sem contexto de sessao (o no-op silencioso)",
    "a resposta humana sai pelo Outbound (criterio 6)",
    "com a janela fechada avisa-se e propoe-se (criterio 6)",
    "idempotencia (criterio 4)",
    "o fecho sob concorrencia (criterio 7)",
    "isolamento (Testes Requeridos: X-03 sobre handoffs)",
    "o SLA de retoma (docs/tecnica/02 §11)",
    # KAM-019, emenda 1.42. O primeiro aparece **duas** vezes na saida, uma por
    # cada lado da prova: na bateria do gate 4 (com o AGR por porta, onde se
    # mede que nenhum `interrupt()` fica pendente) e no ensaio de base (onde se
    # mede que as duas escritas compoem contra um PostgreSQL a serio).
    "a fronteira da retoma (emenda 1.42, credor do criterio 3 do KAM-034)",
    "o fecho, depois da emenda 1.42 (criterio 7)",
    "o pedido que sai",
    "a traducao da resposta",
    "o 503 e o Retry-After",
)

#: Testes que **tem** de ter corrido e passado, pelo nome. Lista curta, com os
#: que dao a letra de cada criterio.
TESTES_OBRIGATORIOS = (
    "**cinco aberturas concorrentes: 1 linha e 1 chamada ao provedor**",
    "**a conta de atendimento: 1 chamada ao provedor e 1 linha**",
    "**a mesma conta do provedor em dois tenants e recusada pela base**",
    "**dois close em paralelo: um escreve e o outro nao casa**",
    "com o contexto de A, as passagens de B nao aparecem",
    "com o contexto de A, uma escrita na passagem de B nao acontece",
    "o SQL_FORA_DO_SLA so ve as do proprio tenant",
    "**uma passagem degradada conta no SLA**",
    "**o account_id do bot nunca vai nulo**",
    "**o inbox e de tipo api e nao de WhatsApp** (criterio 2)",
    "**levanta SemPrivilegioError, e a mensagem diz de quem e o privilegio**",
    "**um segredo esperado vazio recusa tudo**, e e a falha fechada",
    "**um incoming nao e resposta de agente**: e o eco do nosso espelho",
    "**o guarda recusa sempre e a resposta sai**: `doBot: false`",
    "**o mesmo callback duas vezes da uma mensagem**",
    "**sem identificador de mensagem nao se envia**",
    "**nao se envia, e o painel recebe o aviso com o template proposto**",
    # O que o spike mediu, e que nenhum duplo podia dizer.
    "**sao seis pedidos, pela ordem que o spike mediu**",
    "**o inbox e criado com o token do UTILIZADOR e nao da plataforma**",
    "**o set_agent_bot existe, e sem ele nada funciona**",
    "**o contacto vem antes da conversa, e com o token do utilizador**",
    "**a chave opaca nao e o nosso contact_id, e nada nosso sai**",
    "**o espelho usa o externalId no URL e o wamid no corpo**",
    "**o cliente de execucao nao conhece o token da plataforma**",
    "**um callback sem segredo nao consulta nada**",
    "**o resolver do callback e escrito, e nao perdido**",
    "**marcar_aberta sem casar devolve o estado verdadeiro**",
    "**sem `app.tenant_id` o fecho levanta, e nao devolve zero linhas**",
    "**duas chamadas concorrentes: o ON CONFLICT da conta**",
    "**o mesmo utilizador do provedor em dois tenants e recusado**",
    # A fronteira da emenda 1.42, que e o credor do criterio 3 do KAM-034. O
    # defeito que estes prendem nao era uma intercalacao rara: era o caminho
    # feliz, todas as vezes — o HND escrevia `resumed` antes de alguem poder
    # pedir a retoma, o compare-and-set do AGR nao casava linha nenhuma, e o
    # `interrupt()` do `handoff_wait` ficava pendente para sempre.
    "**nenhum interrupt fica pendente num handoff que um humano resolveu**",
    "**o HND nao escreve o status: quem o escreve e o CAS do AGR**",
    "**o corpo da retoma sao os tres campos, e o thread_id vem da linha**",
    "**o resolver escreve-se antes da retoma, e e a unica ordem que funciona**",
    "**dois webhooks duplicados dao UMA retoma**",
    "**o segundo webhook nao reescreve o resolver do primeiro**",
    "**um handoffId de outra conversa nao escreve nem retoma**",
    "**o AGR em baixo levanta, e a passagem fica em waiting**",
    "**o handler do onHumanEvent corre, e corre depois da retoma**",
    "**um close sobre uma passagem em waiting nao escreve nada**",
    "**uma passagem degraded fecha-se, e e a unica que fecha**",
    # O cliente HTTP, onde a traducao da resposta pode errar em silencio.
    "**vai para /internal/resume, com as duas credenciais**",
    "**o secret do bot e o deste tenant, lido do prefixo do thread_id**",
    "**o corpo tem os tres campos e mais nenhum**",
    "**401 levanta, e nao se engole**",
    "**o segredo nao vai na mensagem do erro nem a registo**",
    "**404 recusado levanta, porque e divergencia nossa**",
    "**503 e depois 200: espera o que ele pede e retoma**",
    "**dois 503 levantam: a terceira tentativa e do provedor**",
    "**um Retry-After acima do tecto nao se espera**",
    # E contra a base, que e onde as duas escritas compoem.
    "**o resolver chega a base sem passar pelo AGR, e o status vem do CAS**",
    "**dois webhooks duplicados dao UMA retoma e UM resolver**",
    "**a consulta do thread exige o external_id da conversa**",
    "**a consulta do thread nao atravessa tenants**",
    "**uma passagem em waiting nao se fecha por aqui**",
)

#: Os ficheiros do modulo. A cobertura mede-se em **cada um**.
#:
#: O `chatwoot.ts` **esta** aqui, ao contrario do que a suite da saida fez com o
#: `cliente.ts`, e a diferenca e que este tem bateria propria com o `fetch` por
#: porta: o `hnd.chatwoot.test.ts` exercita os caminhos que podem errar em
#: silencio — o `account_id` do bot, o tipo do *inbox*, a troca dos dois tokens
#: e a diferenca entre 4xx e 5xx. Medi-lo aqui nao lhe da uma cobertura que
#: diga so que o ensaio nao abre socket.
#: O `resposta.ts` entrou **depois** de a suite ter passado sem ele, e a
#: licao vale mais do que o ficheiro: uma bateria que o gate nao corre e uma
#: bateria que apodrece em silencio. Os 89 testes do `node --test` incluiam-na
#: pelo glob `tests/hnd.*.test.ts`; esta lista, que e o que o CI usa, nao.
FICHEIROS_DO_MODULO = (
    "assinatura.ts",
    "chatwoot.ts",
    "consultas.ts",
    "contrato.ts",
    "estados.ts",
    "eventos.ts",
    "metricas.ts",
    "provedor.ts",
    "resposta.ts",
    "retoma.ts",
    "index.ts",
)


def _cobertura(lcov: str) -> dict[str, tuple[int, int]]:
    """ficheiro de `src/hnd/` -> (linhas cobertas, linhas encontradas)."""
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
            if "/src/hnd/" in f"/{actual}":
                medidas[actual.rsplit("/", 1)[-1]] = (cobertas, encontradas)
            actual = None
    return medidas


class TestModuloDoHandoff(ComBase):
    """Corre os testes em Node **uma vez**, e depois olha para o que ficou."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.saida = Path(tempfile.mkdtemp(prefix="kamba-handoff-"))
        cls.execucao = node.correr(
            [
                "--test",
                # Um ficheiro de cada vez: o ensaio de base conta linhas de
                # `handoffs` do tenant inteiro e o provedor falso conta chamadas
                # num contador unico — dois ficheiros em paralelo veriam as
                # contagens um do outro.
                "--test-concurrency=1",
                "--experimental-test-coverage",
                "--test-reporter=tap",
                "--test-reporter-destination=stdout",
                "--test-reporter=lcov",
                "--test-reporter-destination={saida}",
                *FICHEIROS,
            ],
            cls.saida / "handoff.lcov",
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

        A mesma funcao do `tests_chr` e do `tests_outbound`, e pela mesma razao
        medida la: o relatorio de cobertura ocupa milhares de linhas no fim da
        saida, e um `escrito[-6000:]` na mensagem de falha mostrava **so** isso.
        """
        linhas = cls.escrito.splitlines()
        partes: list[str] = []
        for indice, linha in enumerate(linhas):
            if re.match(r"^\s*not ok \d+ - ", linha):
                partes.append("\n".join(linhas[indice : indice + 30]))
        resumo = [l for l in linhas if re.match(r"^# (tests|pass|fail) \d+$", l)]
        return "\n\n".join([*partes, " | ".join(resumo)]) or cls.escrito[-4000:]

    def test_os_testes_do_handoff_passam(self) -> None:
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

    def test_os_grupos_correram_todos(self) -> None:
        """Um grupo que desapareca e uma propriedade que deixou de se provar."""
        for grupo in GRUPOS:
            with self.subTest(grupo=grupo):
                self.assertIn(grupo, self.tap)

    def test_os_testes_obrigatorios_passaram(self) -> None:
        """Pelo nome, e com `ok` a frente: a letra de cada criterio."""
        for nome in TESTES_OBRIGATORIOS:
            with self.subTest(teste=nome):
                self.assertRegex(self.tap, rf"(?m)^\s*ok \d+ - {re.escape(nome)}$")

    def test_a_cobertura_do_modulo_e_pelo_menos_a_do_estrato(self) -> None:
        """O gate 4 nao tem base de dados; a cobertura de `src/hnd/` mede-se aqui.

        O limiar e **lido** de `ci/thresholds.yaml`, do estrato `restante`, e
        nao escrito aqui: dois numeros em dois sitios divergem.

        **E `restante` e nao `critico`, pela mesma decisao escrita que a saida
        tomou.** Os padroes que entraram no estrato `critico` entraram porque o
        DoD do ticket respectivo exigia >= 90%; o DoD do KAM-019 diz «cobertura
        >= limiar», sem numero, e alterar `ci/thresholds.yaml` pede **dois
        revisores** (o proprio ficheiro o diz). Nao se alarga um ficheiro de
        limiares para marcar uma caixa que nao pede o numero.
        """
        lcov = self.saida / "handoff.lcov"
        self.assertTrue(lcov.is_file(), f"nao houve LCOV:\n{self.escrito[-3000:]}")
        medidas = _cobertura(lcov.read_text(encoding="utf-8"))
        limiares = load_file(node.RAIZ / "ci" / "thresholds.yaml")
        minimo = next(
            int(e["minimo_linhas"])
            for e in limiares["estratos"]
            if e["nome"] == "restante"
        )
        em_falta = [f for f in FICHEIROS_DO_MODULO if f not in medidas]
        self.assertEqual(
            em_falta, [], f"sem medida: {em_falta}; medidos: {sorted(medidas)}"
        )
        for ficheiro in FICHEIROS_DO_MODULO:
            cobertas, encontradas = medidas[ficheiro]
            with self.subTest(ficheiro=ficheiro):
                if encontradas == 0:
                    continue
                percentagem = cobertas * 100 // encontradas
                print(f"    cobertura {ficheiro}: {percentagem}% ({cobertas}/{encontradas})")
                self.assertGreaterEqual(
                    percentagem,
                    minimo,
                    f"{ficheiro}: {percentagem}% < {minimo}% "
                    f"({cobertas}/{encontradas} linhas)",
                )
