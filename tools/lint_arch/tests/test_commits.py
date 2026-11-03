"""As mensagens dos *commits* do intervalo do PR — KAM-174.

Dois eixos, e o segundo e o que da substancia ao ticket:

* **A decisao do intervalo**, por accionamento. Vive numa funcao pura porque nao
  ha *lint* de *workflows* neste repositorio: uma condicao escrita em YAML nao
  seria verificavel por teste nenhum.
* **Qual** intervalo. O ticket escolhe `pai1..pai2` do *merge ref* e recusa o do
  *gate* 9, e a diferenca entre os dois **so** aparece quando a `main` anda
  enquanto o PR esta aberto. Um teste que use um *commit* historico de `main` nao
  discrimina nada: esse fica fora dos dois, e passaria com qualquer das duas
  implementacoes. E o que `TestOsDoisIntervalos` constroi.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from lint_arch import canario_commits, commits, conventions

ROOT = Path(__file__).resolve().parents[3]
CONVENTIONS = ROOT / "tools" / "conventions.json"

#: Um assunto fora da forma, sem tipo — a classe do `29778f3`.
#:
#: O numero e o do exemplar real e **nao** um inventado: o `lint_refs` varre este
#: ficheiro e exige que cada identificador de ticket exista no §4 do
#: `specs/INDICE.md`. Um numero inventado num literal de teste e uma referencia
#: invalida como qualquer outra — medido, deu dois achados.
FORA_DA_FORMA = "KAM-038 — um assunto sem tipo que nenhum portao leu"


def _rules() -> conventions.Conventions:
    return conventions.load(CONVENTIONS)


def _git(raiz: Path, *argumentos: str) -> str:
    return subprocess.run(
        ["git", *argumentos],
        cwd=raiz,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _iniciar(raiz: Path) -> None:
    _git(raiz, "init", "--initial-branch=main", "--quiet")
    _git(raiz, "config", "user.email", "teste@kamba.local")
    _git(raiz, "config", "user.name", "teste")
    # A maquina de quem corre os testes pode ter `commit.gpgsign` ligado.
    _git(raiz, "config", "commit.gpgsign", "false")


def _commit(raiz: Path, ficheiro: str, mensagem: str) -> str:
    with (raiz / ficheiro).open("a", encoding="utf-8") as handle:
        handle.write(f"{mensagem}\n")
    _git(raiz, "add", ficheiro)
    # `--no-verify`: um `core.hooksPath` global de quem corre os testes recusaria
    # o commit fora da forma, que e precisamente o commit de que estes testes
    # precisam.
    _git(raiz, "commit", "--no-verify", "-m", mensagem)
    return _git(raiz, "rev-parse", "HEAD")


class TestDecidirIntervalo(unittest.TestCase):
    """Criterio 5: cada accionamento pelo nome, e nada deixado ao caso."""

    MERGE = "a" * 40

    def test_pull_request_da_o_intervalo_dos_dois_pais(self) -> None:
        intervalo = commits.decidir_intervalo("pull_request", self.MERGE)
        self.assertEqual(intervalo.modo, commits.MODO_INTERVALO)
        self.assertEqual(intervalo.pai1, f"{self.MERGE}^1")
        self.assertEqual(intervalo.pai2, f"{self.MERGE}^2")

    def test_os_tres_accionamentos_que_decidem_um_merge_exigem_intervalo(self) -> None:
        for accionamento in ("pull_request", "pull_request_target", "merge_group"):
            with self.subTest(accionamento=accionamento):
                self.assertIsNone(
                    commits.ACCIONAMENTOS[accionamento],
                    f"{accionamento} decide um merge: o intervalo e obrigatorio",
                )
                with self.assertRaises(commits.IntervaloInvalido):
                    commits.decidir_intervalo(accionamento, "")

    def test_push_nao_corre_a_passagem_e_declara_o_modo(self) -> None:
        """O criterio 5 di-lo por extenso, e a razao e que nao tem correccao.

        O que chega por `push` ja fundiu, e um commit de `main` nao se reescreve
        (criterio 7). O gate 2 e contexto obrigatorio do *ruleset* de `main`, pelo
        que um vermelho aqui travava o repositorio depois de cada merge.
        """
        intervalo = commits.decidir_intervalo("push", "b" * 40)
        self.assertEqual(intervalo.modo, commits.MODO_SEM_PASSAGEM)
        self.assertIn("push", intervalo.razao)

    def test_em_push_e_o_accionamento_que_manda_e_nao_a_presenca_do_sha(self) -> None:
        """A divergencia deliberada face ao `decidir_intervalo` do gate 9.

        No gate 9 decide a **presenca da base**. Aqui decide o **accionamento**, e
        tem de ser: em `push` o `github.sha` e um SHA perfeitamente valido, e se a
        presenca de um SHA decidisse, a passagem corria sobre `main` depois de
        cada merge — onde o commit de um squash tem **um** pai, nao ha segundo
        pai, e o gate ficava vermelho sem autor que o pudesse corrigir.
        """
        com_sha = commits.decidir_intervalo("push", "c" * 40)
        sem_sha = commits.decidir_intervalo("push", "")
        self.assertEqual(com_sha.modo, commits.MODO_SEM_PASSAGEM)
        self.assertEqual(sem_sha.modo, commits.MODO_SEM_PASSAGEM)
        self.assertEqual(com_sha.razao, sem_sha.razao)

    def test_workflow_dispatch_nao_corre_a_passagem(self) -> None:
        intervalo = commits.decidir_intervalo("workflow_dispatch", "")
        self.assertEqual(intervalo.modo, commits.MODO_SEM_PASSAGEM)

    def test_execucao_local_declara_o_modo_em_vez_de_passar_em_silencio(self) -> None:
        intervalo = commits.decidir_intervalo("", "")
        self.assertEqual(intervalo.modo, commits.MODO_SEM_PASSAGEM)
        self.assertIn("local", intervalo.razao)

    def test_accionamento_nao_escrito_fica_vermelho(self) -> None:
        """Fail-closed, no padrao do `SEM_INTERVALO` do gate 9."""
        with self.assertRaises(commits.IntervaloInvalido) as capturado:
            commits.decidir_intervalo("schedule", "d" * 40)
        self.assertIn("nao esta escrito", str(capturado.exception))

    def test_um_merge_ref_a_zeros_conta_como_ausente(self) -> None:
        """E o `before` que o GitHub poe num ramo novo."""
        with self.assertRaises(commits.IntervaloInvalido):
            commits.decidir_intervalo("pull_request", "0" * 40)

    def test_os_cinco_accionamentos_do_criterio_5_estao_escritos(self) -> None:
        for accionamento in (
            "pull_request",
            "push",
            "workflow_dispatch",
            "merge_group",
            "pull_request_target",
        ):
            self.assertIn(accionamento, commits.ACCIONAMENTOS)
        # Mais a execucao local, que nao e um accionamento do GitHub.
        self.assertIn("", commits.ACCIONAMENTOS)

    def test_exigem_commits_deriva_dos_accionamentos(self) -> None:
        """Duas listas de accionamentos divergem; esta deriva da outra."""
        self.assertEqual(
            commits.EXIGEM_COMMITS,
            frozenset(
                nome for nome, razao in commits.ACCIONAMENTOS.items() if razao is None
            ),
        )


class TestExigirCommits(unittest.TestCase):
    def test_zero_commits_num_accionamento_que_decide_merge_e_erro(self) -> None:
        for accionamento in sorted(commits.EXIGEM_COMMITS):
            with self.subTest(accionamento=accionamento):
                with self.assertRaises(commits.IntervaloInvalido):
                    commits.exigir_commits(accionamento, 0)

    def test_zero_commits_fora_desses_accionamentos_nao_e_erro(self) -> None:
        commits.exigir_commits("push", 0)
        commits.exigir_commits("", 0)

    def test_com_commits_nunca_e_erro(self) -> None:
        for accionamento in sorted(commits.EXIGEM_COMMITS):
            commits.exigir_commits(accionamento, 1)


class _ComArvore(unittest.TestCase):
    """Um repositorio descartavel com a forma de um *merge ref* do GitHub.

    **Uma arvore por classe, e nao por teste.** Construi-la custa oito invocacoes
    do `git`, e em Windows isso sao segundos: medido a 2026-11-03, com uma arvore
    por teste esta suite levava 88 s, dos quais a maior parte era o mesmo
    repositorio construido vinte vezes. A mesma razao pela qual o
    `test_conventions` le o corpus uma vez.

    **As subclasses que usam esta arvore nao a alteram** — e a condicao que torna
    a partilha legitima. Um teste que acrescente *commits* leva arvore propria
    (ver `TestMensagemInteira`), porque uma suite cujo resultado dependa da ordem
    de execucao e exactamente o que o KAM-173 acabou de fechar no *gate* 4.
    """

    raiz: Path
    rules: conventions.Conventions

    @classmethod
    def setUpClass(cls) -> None:
        # `ignore_cleanup_errors`: em Windows o git deixa objectos em
        # leitura-apenas e a limpeza levanta `PermissionError`.
        temporaria = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.addClassCleanup(temporaria.cleanup)
        cls.raiz = Path(temporaria.name)
        cls.rules = _rules()
        _iniciar(cls.raiz)
        cls.construir()

    @classmethod
    def construir(cls) -> None:
        """A arvore de cada subclasse."""
        raise NotImplementedError


class TestVarrimentoDoIntervalo(_ComArvore):
    base: str
    bom: str
    mau: str
    merge: str

    @classmethod
    def construir(cls) -> None:
        cls.base = _commit(cls.raiz, "historia.txt", "chore(KAM-174): o commit da base")
        _git(cls.raiz, "checkout", "--quiet", "-b", "ramo")
        cls.bom = _commit(
            cls.raiz, "ramo.txt", "fix(KAM-174): o commit conforme do ramo"
        )
        cls.mau = _commit(cls.raiz, "ramo.txt", FORA_DA_FORMA)
        _git(cls.raiz, "checkout", "--quiet", "main")
        # O merge **a partir da base**, que e a ordem de pais que o GitHub produz:
        # pai 1 = base, pai 2 = cabeca do ramo. Um `git merge main` de dentro do
        # ramo daria a ordem inversa, e ha um desses no proprio repositorio
        # (`33af7f5`).
        _git(
            cls.raiz,
            "merge",
            "--no-ff",
            "--no-verify",
            "-m",
            f"Merge {cls.mau} into {cls.base}",
            "ramo",
        )
        cls.merge = _git(cls.raiz, "rev-parse", "HEAD")

    def test_a_ordem_dos_pais_e_a_do_merge_ref_do_github(self) -> None:
        """A premissa do criterio 3, verificada na arvore que os testes usam."""
        self.assertEqual(_git(self.raiz, "rev-parse", f"{self.merge}^1"), self.base)
        self.assertEqual(_git(self.raiz, "rev-parse", f"{self.merge}^2"), self.mau)

    def test_o_intervalo_tem_os_commits_do_ramo_e_mais_nenhum(self) -> None:
        resultado = commits.verificar_intervalo(
            self.raiz, f"{self.merge}^1", f"{self.merge}^2", self.rules
        )
        self.assertEqual(resultado.commits, 2)

    def test_um_assunto_fora_da_forma_reprova_e_a_mensagem_diz_qual_e_o_commit(
        self,
    ) -> None:
        resultado = commits.verificar_intervalo(
            self.raiz, f"{self.merge}^1", f"{self.merge}^2", self.rules
        )
        self.assertEqual(len(resultado.achados), 1, resultado.achados)
        achado = resultado.achados[0]
        self.assertEqual(achado.sha, self.mau)
        self.assertEqual(achado.assunto, FORA_DA_FORMA)
        # O criterio de aceitacao pede que a mensagem diga **qual** e o commit.
        self.assertIn(self.mau[:12], str(achado))

    def test_um_assunto_conforme_passa(self) -> None:
        resultado = commits.verificar_intervalo(
            self.raiz, f"{self.merge}^1", f"{self.merge}^2", self.rules
        )
        encontrados = {achado.sha for achado in resultado.achados}
        self.assertNotIn(self.bom, encontrados)

    def test_o_commit_da_base_nao_entra_no_intervalo(self) -> None:
        resultado = commits.verificar_intervalo(
            self.raiz, f"{self.merge}^1", f"{self.merge}^2", self.rules
        )
        self.assertNotIn(self.base, {achado.sha for achado in resultado.achados})

    def test_o_merge_sintetico_fica_fora_por_construcao(self) -> None:
        """E **nao** por cair na isencao `^Merge `, que e o que isto prova.

        Com as `exemptHeaderPatterns` retiradas, um `Merge ...` que estivesse
        dentro do intervalo apareceria nos achados. Nao aparece, porque o merge e
        a **cabeca** do `rev-list` e nao um elemento dele.
        """
        sem_isencoes = dataclasses.replace(self.rules, exempt_header_patterns=())
        resultado = commits.verificar_intervalo(
            self.raiz, f"{self.merge}^1", f"{self.merge}^2", sem_isencoes
        )
        self.assertNotIn(self.merge, {achado.sha for achado in resultado.achados})
        # E a passagem continua a varrer: o assunto mau continua a ser encontrado.
        self.assertIn(self.mau, {achado.sha for achado in resultado.achados})


class TestMensagemInteira(_ComArvore):
    """A mensagem vai inteira (`%B`) e nao so o assunto.

    Arvore propria porque esta classe acrescenta *commits*: partilhar a de
    `TestVarrimentoDoIntervalo` punha o resultado a depender da ordem de
    execucao.
    """

    colado: str
    merge: str

    @classmethod
    def construir(cls) -> None:
        base = _commit(cls.raiz, "historia.txt", "chore(KAM-174): o commit da base")
        _git(cls.raiz, "checkout", "--quiet", "-b", "ramo")
        cls.colado = _commit(
            cls.raiz,
            "outro.txt",
            "fix(KAM-174): o assunto esta conforme\no corpo esta colado",
        )
        _git(cls.raiz, "checkout", "--quiet", "main")
        _git(
            cls.raiz,
            "merge",
            "--no-ff",
            "--no-verify",
            "-m",
            f"Merge {cls.colado} into {base}",
            "ramo",
        )
        cls.merge = _git(cls.raiz, "rev-parse", "HEAD")

    def test_um_corpo_colado_ao_cabecalho_reprova(self) -> None:
        """Dar so o assunto fazia o gate aceitar o que o *hook* recusa.

        O `check_commit_message` tambem le `body-leading-blank`. Este commit e
        conforme **no assunto** e nao conforme **na mensagem**, e e a mensagem que
        o *hook* le — pelo que um varrimento que lesse so a primeira linha abria
        a divergencia que `tools/conventions.json` existe para impedir.
        """
        resultado = commits.verificar_intervalo(
            self.raiz, f"{self.merge}^1", f"{self.merge}^2", self.rules
        )
        self.assertIn(self.colado, {achado.sha for achado in resultado.achados})


class TestOsDoisIntervalos(_ComArvore):
    """O teste que distingue o intervalo do criterio 3 do intervalo do gate 9.

    A forma e a unica que discrimina: um commit **fora da forma** que funde em
    `main` **depois** do SHA de base, enquanto o PR esta aberto. Com um commit
    historico de `main` os dois intervalos dao o mesmo (nenhum o ve), e o teste
    passaria com qualquer das duas implementacoes — que e a armadilha que o
    ticket nomeia.

        B0 ──────────── B1 (fora da forma, fundido depois)──── M (merge ref)
         \\                                                   /
          └── C1 (conforme, do PR) ─────────────────────────┘

    criterio 3:  M^1..M^2 = B1..C1  ->  {C1}          B1 **fora**
    gate 9:      B0..M              ->  {C1, B1, M}   B1 **dentro**
    """

    base_do_evento: str
    do_pr: str
    de_outro: str
    merge: str

    @classmethod
    def construir(cls) -> None:
        # B0: a ponta de `main` quando o PR abriu. E o `base.sha` do evento.
        cls.base_do_evento = _commit(
            cls.raiz, "historia.txt", "chore(KAM-174): a ponta de main quando o PR abriu"
        )
        # O ramo do PR, com um commit conforme.
        _git(cls.raiz, "checkout", "--quiet", "-b", "ramo")
        cls.do_pr = _commit(cls.raiz, "ramo.txt", "fix(KAM-174): o unico commit deste PR")
        # `main` anda **enquanto o PR esta aberto**, e o que funde esta fora da
        # forma. E um commit de outra pessoa, que o autor deste PR nao pode
        # corrigir: os commits de `main` nao se reescrevem (criterio 7).
        _git(cls.raiz, "checkout", "--quiet", "main")
        cls.de_outro = _commit(cls.raiz, "historia.txt", FORA_DA_FORMA)
        _git(
            cls.raiz,
            "merge",
            "--no-ff",
            "--no-verify",
            "-m",
            f"Merge {cls.do_pr} into {cls.de_outro}",
            "ramo",
        )
        cls.merge = _git(cls.raiz, "rev-parse", "HEAD")

    def test_o_intervalo_do_criterio_3_nao_ve_o_commit_de_outro(self) -> None:
        resultado = commits.verificar_intervalo(
            self.raiz, f"{self.merge}^1", f"{self.merge}^2", self.rules
        )
        self.assertEqual(resultado.achados, (), resultado.achados)
        self.assertEqual(resultado.commits, 1)

    def test_o_intervalo_do_gate_9_ve_o_commit_de_outro_e_avermelharia_o_pr(
        self,
    ) -> None:
        """A razao pela qual o criterio 3 divergir do gate 9 nao e preferencia.

        O mesmo codigo, o mesmo PR, o outro intervalo: o achado e um commit que o
        autor do PR nao escreveu e nao pode corrigir. Um portao que avermelha por
        acto de terceiro e um portao que se aprende a ignorar.
        """
        resultado = commits.verificar_intervalo(
            self.raiz, self.base_do_evento, self.merge, self.rules
        )
        encontrados = {achado.sha for achado in resultado.achados}
        self.assertIn(self.de_outro, encontrados)

    def test_com_o_intervalo_do_gate_9_o_merge_sintetico_so_escapa_pela_isencao(
        self,
    ) -> None:
        """E a segunda metade da razao do criterio 3, e a mais fina.

        Com o intervalo do gate 9 o merge sintetico **esta dentro** do conjunto, e
        o que o deixa passar e a isencao `^Merge `. Com o intervalo do criterio 3
        ele esta fora por construcao. A diferenca importa porque o criterio 8
        declara as `exemptHeaderPatterns` intocaveis: depender delas para excluir
        o merge sintetico era pendurar o desenho numa lista que o ticket promete
        nao endurecer.
        """
        sem_isencoes = dataclasses.replace(self.rules, exempt_header_patterns=())
        pelo_gate_9 = commits.verificar_intervalo(
            self.raiz, self.base_do_evento, self.merge, sem_isencoes
        )
        self.assertIn(self.merge, {achado.sha for achado in pelo_gate_9.achados})

        pelo_criterio_3 = commits.verificar_intervalo(
            self.raiz, f"{self.merge}^1", f"{self.merge}^2", sem_isencoes
        )
        self.assertNotIn(
            self.merge, {achado.sha for achado in pelo_criterio_3.achados}
        )


class TestCloneRaso(unittest.TestCase):
    def test_um_clone_raso_fica_vermelho_em_vez_de_varrer_pela_metade(self) -> None:
        """Criterio 4: com `fetch-depth` a 1 nao ha historia de ramo para ler.

        Um intervalo truncado daria um conjunto pequeno e um gate verde que nao
        significa nada, que e o modo de falha que o `fetch-depth: 0` do job
        fecha.
        """
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as pasta:
            origem = Path(pasta) / "origem"
            origem.mkdir()
            _iniciar(origem)
            _commit(origem, "a.txt", "chore(KAM-174): o primeiro")
            _commit(origem, "a.txt", "chore(KAM-174): o segundo")
            raso = Path(pasta) / "raso"
            subprocess.run(
                ["git", "clone", "--depth", "1", origem.as_uri(), str(raso)],
                check=True,
                capture_output=True,
            )
            with self.assertRaises(commits.IntervaloInvalido) as capturado:
                commits.verificar_intervalo(raso, "HEAD~1", "HEAD", _rules())
            self.assertIn("raso", str(capturado.exception))


class TestCanario(unittest.TestCase):
    """O canario corre no portao; isto verifica que ele nao se pode esvaziar."""

    def test_o_canario_esta_verde_com_as_regras_do_repositorio(self) -> None:
        falhas, _ = canario_commits.canario(_rules())
        self.assertEqual(falhas, [])

    def test_cada_regra_prendida_tem_um_caso_negativo(self) -> None:
        prendidas = {nome for nome, _ in canario_commits.REGRAS_DA_MENSAGEM}
        usadas = {regra for _, regra in canario_commits.NEGATIVOS}
        self.assertEqual(
            prendidas - usadas,
            set(),
            "ha regra prendida sem caso negativo que a prove",
        )
        self.assertEqual(
            usadas - prendidas,
            set(),
            "ha caso negativo a invocar uma regra que nao esta prendida",
        )

    def test_os_padroes_sao_ancorados(self) -> None:
        """A licao que o canario do titulo pagou: um fragmento marca a regra errada."""
        for nome, padrao in canario_commits.REGRAS_DA_MENSAGEM:
            with self.subTest(regra=nome):
                self.assertTrue(
                    padrao.startswith("^"),
                    f"o padrao de {nome!r} nao esta ancorado no inicio",
                )

    def test_cada_padrao_e_satisfeito_por_uma_regra_so(self) -> None:
        """Dois padroes que a mesma mensagem satisfaz nao distinguem nada."""
        rules = _rules()
        for mensagem, regra in canario_commits.NEGATIVOS:
            problemas = conventions.check_commit_message(mensagem, rules)
            batem = {
                nome
                for nome, padrao in canario_commits.REGRAS_DA_MENSAGEM
                if any(re.match(padrao, p) for p in problemas)
            }
            with self.subTest(mensagem=" ".join(mensagem.split())[:40]):
                self.assertIn(regra, batem)

    def test_o_canario_fica_vermelho_quando_uma_regra_deixa_de_morder(self) -> None:
        """Um canario que nunca se ve vermelho nao prova nada.

        Mutam-se as regras uma a uma e exige-se vermelho em cada mutacao. E a
        mesma forma das `mutacoes.py` desta pasta: uma mutacao sobrevivente e um
        buraco na cobertura.
        """
        rules = _rules()
        mutacoes = {
            "descricao longa": dataclasses.replace(rules, subject_max_length=10_000),
            "descricao curta": dataclasses.replace(rules, subject_min_length=0),
            "ponto final": dataclasses.replace(
                rules, subject_ends_without_period=False
            ),
            "minuscula": dataclasses.replace(rules, subject_starts_lowercase=False),
            "cabecalho longo": dataclasses.replace(rules, header_max_length=10_000),
            "corpo": dataclasses.replace(rules, body_leading_blank=False),
            "rodape": dataclasses.replace(rules, footer_leading_blank=False),
            "isencoes": dataclasses.replace(rules, exempt_header_patterns=()),
            "ambito": dataclasses.replace(rules, scope_pattern="^.*$"),
        }
        for nome, mutado in mutacoes.items():
            with self.subTest(mutacao=nome):
                falhas, _ = canario_commits.canario(mutado)
                self.assertNotEqual(
                    falhas,
                    [],
                    f"a mutacao {nome!r} sobreviveu ao canario",
                )

    def test_o_merge_por_omissao_do_git_esta_nos_positivos(self) -> None:
        """A isencao `^Merge ` e o que mantem esta regra pequena.

        Sem ela, trazer a `main` para dentro de um PR passava a exigir baptizar o
        merge a mao — uma regra pequena a morder uma operacao frequente. Medido a
        2026-11-03: ha 12 merges de forma por omissao nos ultimos 300 commits de
        `main`.
        """
        self.assertTrue(
            any(p.startswith("Merge branch ") for p in canario_commits.POSITIVOS),
            "sem este positivo, ninguem repara no dia em que a isencao sair",
        )


if __name__ == "__main__":
    unittest.main()
