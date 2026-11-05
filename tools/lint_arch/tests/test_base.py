"""A base do ramo, lida pela origem — KAM-180.

Tres eixos, e o segundo e o terceiro sao o que da substancia ao ticket:

* **As duas direccoes.** Um ramo cortado de `refs/remotes/publico/main` sai
  conforme, e um ramo cortado da linha antiga sai recusado. Sem o caso negativo,
  um comando que dissesse sempre «conforme» passava.
* **O controlo.** A decisao nao pode vir da pasta `.claude/skills/`, e a *fixture*
  deste ficheiro poe o sinal da pasta **invertido** nas duas linhas: a linha
  errada leva `software-factory` e a certa leva `agentic-engineering`. Qualquer
  implementacao que leia a pasta responde **ao contrario nos dois sentidos**, e
  nao apenas num. A razao esta no cabecalho de `base.py`: a pasta muda sozinha
  quando se ramifica, pelo que responde «onde estou agora» e nao «fui cortado».
* **As armadilhas de medicao, recusadas por ensaio e nao por comentario.** O
  `merge-base` sai 1 **sem saida**; o `rev-list --left-right --count` responde um
  par plausivel entre linhas sem antepassado comum; e a variavel sem aspas
  colapsa o `git diff` numa resposta que se le como «nao ha diferenca». Cada uma
  tem o seu caso, e cada um mede o comportamento do git **nesta** maquina em vez
  de confiar na prosa do ticket.

**A *fixture* constroi duas linhas sem antepassado comum**, que e a situacao real
deste repositorio: o `publico` (`albinoJimy/kamba-plataforma`) e o activo e o
`origin` (`albinoJimy/kamba`) e a linha antiga, e `git merge-base` entre as duas
nao responde. Um teste que usasse duas linhas com antepassado comum nao
discriminava nada, porque as tres armadilhas **so existem** sem antepassado
comum.

**E os quatro estados de *reflog* sao construidos, nao simulados.** O ramo
reparado nasce com o *log* desligado e e depois movido com `branch -f`, que e
exactamente o que a aplicacao e a sessao fazem — a aplicacao cria o ramo sem
entrada de *log*, e a sessao repara-o com um `Reset`. E foi assim que se
confirmou, em `claude/manual-provider-auditado-e03ef3`, que o `git reflog show`
nu responde `conforme` onde o ficheiro cru responde `recusado`.
"""

from __future__ import annotations

import ast
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from lint_arch import base, cli

RAIZ = Path(__file__).resolve().parents[3]

#: O *commit* real em que os *worktrees* deste repositorio nasceram — o *merge* do
#: PR `#47` da linha antiga. Entra aqui so como documentacao do que a *fixture*
#: imita; nenhum caso depende de ele existir, para que a bateria corra tambem na
#: copia que o arreio de mutacao faz fora do repositorio.
COMMIT_DA_LINHA_ANTIGA = "f34499069b81d2fe856fdf99ff68ff1219534417"


def _codigo_executavel() -> str:
    """O `base.py` **sem as docstrings**, para os controlos estaticos.

    As docstrings nomeiam a pasta das *skills* e o `rev-list` de proposito: e
    nelas que esta escrito porque e que nenhum dos dois serve para decidir.
    Varrer o ficheiro inteiro punha os dois controlos vermelhos pela
    documentacao que eles existem para exigir — medido, foi o que aconteceu a
    primeira versao deste ficheiro.
    """
    arvore = ast.parse((RAIZ / "tools" / "lint_arch" / "base.py").read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if not isinstance(
            no, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        corpo = no.body
        if (
            corpo
            and isinstance(corpo[0], ast.Expr)
            and isinstance(corpo[0].value, ast.Constant)
            and isinstance(corpo[0].value.value, str)
        ):
            corpo[0].value.value = ""
    return ast.unparse(arvore)


def _git(raiz: Path, *argumentos: str) -> str:
    return subprocess.run(
        ["git", *argumentos],
        cwd=raiz,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _bruto(raiz: Path, *argumentos: str) -> subprocess.CompletedProcess[str]:
    """Como `_git`, mas **sem `check`**: aqui o codigo de saida e a medicao."""
    return subprocess.run(
        ["git", *argumentos], cwd=raiz, capture_output=True, text=True
    )


def _iniciar(raiz: Path) -> None:
    _git(raiz, "init", "--initial-branch=antiga", "--quiet")
    _git(raiz, "config", "user.email", "teste@kamba.local")
    _git(raiz, "config", "user.name", "teste")
    # A maquina de quem corre os testes pode ter `commit.gpgsign` ligado.
    _git(raiz, "config", "commit.gpgsign", "false")


def _commit(raiz: Path, ficheiro: str, mensagem: str) -> str:
    alvo = raiz / ficheiro
    alvo.parent.mkdir(parents=True, exist_ok=True)
    with alvo.open("a", encoding="utf-8") as handle:
        handle.write(f"{mensagem}\n")
    _git(raiz, "add", "-A")
    # `--no-verify`: um `core.hooksPath` global de quem corre os testes podia
    # recusar estas mensagens, que sao de *fixture* e nao de producao.
    _git(raiz, "commit", "--no-verify", "-m", mensagem)
    return _git(raiz, "rev-parse", "HEAD")


class ComDuasLinhas(unittest.TestCase):
    """Duas linhas de historia **sem antepassado comum**, como o repositorio real.

    `antiga` e o analogo do `origin`, onde o `EnterWorktree` ramifica; a
    referencia `refs/remotes/publico/main` e o analogo da linha que conta.

    **O sinal da pasta vai invertido de proposito** — ver o cabecalho do modulo.
    """

    def setUp(self) -> None:
        self.directorio = tempfile.TemporaryDirectory(prefix="kam180-")
        self.addCleanup(self.directorio.cleanup)
        self.raiz = Path(self.directorio.name) / "repo"
        self.raiz.mkdir()
        _iniciar(self.raiz)

        # --- a linha antiga, com a pasta da linha CERTA (o controlo) ---
        _commit(self.raiz, ".claude/skills/software-factory/SKILL.md", "base antiga")
        self.antiga = _commit(self.raiz, "antiga.txt", "o merge do PR 47")

        # --- a linha que conta, com a pasta da linha ERRADA (o controlo) ---
        _git(self.raiz, "checkout", "--orphan", "publica", "--quiet")
        _git(self.raiz, "rm", "-rf", "--quiet", ".")
        _commit(
            self.raiz, ".claude/skills/agentic-engineering/SKILL.md", "base publica"
        )
        self.publica = _commit(self.raiz, "publica.txt", "a linha que conta")
        _git(
            self.raiz,
            "update-ref",
            base.REFERENCIA_PADRAO,
            self.publica,
        )

        # A *fixture* nao serve se as duas linhas tiverem antepassado comum: e
        # dele que depende cada uma das tres armadilhas. Verifica-se aqui, uma
        # vez, em vez de se confiar no `--orphan`.
        self.assertEqual(
            _bruto(self.raiz, "merge-base", self.antiga, self.publica).returncode,
            1,
            "a fixture tem de ter duas linhas sem antepassado comum",
        )

    # --- construtores de ramo, um por estado de reflog -----------------------

    def _ramo_criado_em(self, nome: str, commit: str) -> str:
        """Um ramo com entrada de criacao: coluna antiga nula, nova = `commit`."""
        _git(self.raiz, "branch", nome, commit)
        return nome

    def _ramo_sem_reflog(self, nome: str, commit: str) -> str:
        """Um ramo sem *log* nenhum — o estado em que a aplicacao deixa o `claude/…`.

        Medido no ramo que esta sessao recebeu: nao havia ficheiro
        `logs/refs/heads/claude/…` nenhum.
        """
        _git(self.raiz, "-c", "core.logAllRefUpdates=false", "branch", nome, commit)
        return nome

    def _ramo_reparado(self, nome: str) -> str:
        """Nasce na linha errada **sem** *log*, e e depois movido para a certa.

        E a sequencia real: a aplicacao cria o ramo sem entrada de *log*, a
        sessao repara-o, e **depois trabalha**. A primeira entrada do *reflog*
        passa a ser o `Reset`, cuja coluna **nova** e o *commit* de depois da
        reparacao e cuja coluna **antiga** e a origem verdadeira.

        **O *commit* por cima nao e enfeite.** Sem ele o *reflog* tem uma entrada
        so, a primeira e a ultima coincidem, e um instrumento que lesse a
        **ultima** entrada passava esta bateria por acidente. O exemplar real
        (`claude/manual-provider-auditado-e03ef3`) tem o `Reset` seguido de um
        `commit`, que e o estado em que uma sessao reparada fica.
        """
        self._ramo_sem_reflog(nome, self.antiga)
        _git(
            self.raiz,
            "-c",
            "core.logAllRefUpdates=true",
            "branch",
            "-f",
            nome,
            base.REFERENCIA_PADRAO,
        )
        _git(self.raiz, "checkout", "--quiet", nome)
        _commit(self.raiz, "trabalho.txt", "feat(KAM-180): o trabalho da sessao")
        return nome

    def _avaliar(self, ramo: str) -> base.Veredicto:
        return base.avaliar(self.raiz, ramo)


class TestAsDuasDireccoes(ComDuasLinhas):
    """Criterio 1: a pergunta responde-se, e responde-se nos dois sentidos."""

    def test_ramo_cortado_da_linha_certa_sai_conforme(self) -> None:
        veredicto = self._avaliar(self._ramo_criado_em("feature/KAM-180-certo", self.publica))
        self.assertEqual(veredicto.estado, base.CONFORME)
        self.assertEqual(veredicto.origem, self.publica)
        self.assertEqual(veredicto.codigo, 0)

    def test_ramo_cortado_da_linha_antiga_sai_recusado(self) -> None:
        veredicto = self._avaliar(self._ramo_criado_em("claude/errado-abc123", self.antiga))
        self.assertEqual(veredicto.estado, base.RECUSADO)
        self.assertEqual(veredicto.origem, self.antiga)
        self.assertEqual(veredicto.codigo, 1)

    def test_a_mensagem_do_recusado_nomeia_a_reparacao_exacta(self) -> None:
        """Criterio 4: a reparacao vem na saida, com o comando, e nao e `reset --hard`."""
        veredicto = self._avaliar(self._ramo_criado_em("claude/errado-abc123", self.antiga))
        texto = base.texto_da_reparacao(veredicto)
        # O `fetch` **com refspec**: sem ela so o FETCH_HEAD se move.
        self.assertIn(
            f"git fetch publico main:{base.REFERENCIA_PADRAO} --force", texto
        )
        self.assertIn("git checkout -b fix/KAM-NNN-<slug>", texto)
        # E o nome que o `lint_arch branch` aceita, nao o `claude/…` gerado.
        self.assertNotIn("git checkout -b claude/", texto)
        # O `reset --hard` so pode aparecer para ser **recusado**: esta bloqueado
        # por guarda nesta maquina. Uma linha que o sugerisse era uma reparacao
        # que nao corre.
        for linha in texto.splitlines():
            if "reset --hard" in linha:
                self.assertIn(
                    "Nao", linha, f"o `reset --hard` aparece sem recusa: {linha!r}"
                )

    def test_o_recusado_nunca_imprime_a_palavra_conforme(self) -> None:
        ramo = self._ramo_criado_em("claude/errado-abc123", self.antiga)
        saida, erro = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            codigo = cli.main(["--root", str(self.raiz), "base", ramo])
        self.assertEqual(codigo, 1)
        self.assertIn("RECUSADO", erro.getvalue())
        self.assertEqual(saida.getvalue(), "")
        self.assertNotIn("conforme", erro.getvalue())


class TestOControlo(ComDuasLinhas):
    """Criterio 2: a decisao nao vem da pasta `.claude/skills/`.

    A *fixture* tem o sinal **invertido**, pelo que uma implementacao que o leia
    erra nos **dois** sentidos. Um controlo que so invertesse um lado podia ser
    passado por um comando que respondesse sempre o mesmo.
    """

    def test_origem_errada_com_a_pasta_da_linha_certa_continua_recusada(self) -> None:
        ramo = self._ramo_criado_em("claude/errado-abc123", self.antiga)
        _git(self.raiz, "checkout", "--quiet", ramo)
        # A arvore deste ramo tem `software-factory`, que e o sinal da linha
        # CERTA. A origem e a errada, e e a origem que decide.
        self.assertTrue((self.raiz / ".claude/skills/software-factory").is_dir())
        self.assertFalse((self.raiz / ".claude/skills/agentic-engineering").is_dir())
        self.assertEqual(self._avaliar(ramo).estado, base.RECUSADO)

    def test_origem_certa_com_a_pasta_da_linha_errada_continua_conforme(self) -> None:
        ramo = self._ramo_criado_em("feature/KAM-180-certo", self.publica)
        _git(self.raiz, "checkout", "--quiet", ramo)
        self.assertTrue((self.raiz / ".claude/skills/agentic-engineering").is_dir())
        self.assertFalse((self.raiz / ".claude/skills/software-factory").is_dir())
        self.assertEqual(self._avaliar(ramo).estado, base.CONFORME)

    def test_o_codigo_do_modulo_nao_nomeia_a_pasta_das_skills(self) -> None:
        """O controlo tambem em estatica, e nao so em comportamento.

        Os dois casos acima apanham quem **decida** pela pasta. Este apanha quem
        a leia para «confirmar» — uma leitura que nao muda a decisao hoje e que
        o proximo a mexer aqui promove a decisao sem perceber que ha um controlo.
        Compara-se o codigo **sem a docstring do modulo**, que fala da pasta de
        proposito: e la que esta escrito porque e que ela nao serve.
        """
        executavel = _codigo_executavel()
        for proibido in ("skills", "software-factory", "agentic-engineering"):
            self.assertNotIn(
                proibido,
                executavel,
                f"o codigo de base.py nomeia {proibido!r}: a pasta responde "
                "«onde estou agora» e nao «fui cortado» (KAM-180, criterio 2)",
            )

    def test_o_codigo_do_modulo_nao_usa_rev_list(self) -> None:
        """Armadilha 2, fixada tambem em estatica — ver `TestArmadilhaDoRevList`.

        O par que o `rev-list` devolve e plausivel, pelo que quem o usasse para
        decidir nao daria erro nenhum: daria uma resposta errada com cara de
        resposta. O comportamento esta fixado em `TestArmadilhaDoRevList`; isto
        fixa que o comando nem o chama.
        """
        self.assertNotIn("rev-list", _codigo_executavel())


class TestORamoReparado(ComDuasLinhas):
    """O terceiro caso: origem errada, *reflog* a comecar num `Reset`.

    E o que separa este ticket de um falso negativo. O `git reflog show` nu
    imprime o valor **novo**, que num ramo reparado e o *commit* de **depois** da
    reparacao — e esse esta na linha certa, pelo que a resposta seria «conforme».
    """

    def test_o_ramo_reparado_continua_recusado(self) -> None:
        ramo = self._ramo_reparado("claude/reparado-abc123")
        veredicto = self._avaliar(ramo)
        self.assertEqual(veredicto.estado, base.RECUSADO)
        self.assertEqual(veredicto.origem, self.antiga)
        self.assertIn("valor antigo", veredicto.razao)

    def test_a_ponta_do_ramo_reparado_ja_carrega_a_linha_certa(self) -> None:
        """A premissa do caso: sem isto, o caso acima nao discriminava nada.

        A reparacao tem de ter acontecido de verdade — a ponta do ramo descende
        da linha certa. Se descendesse da errada, ler a coluna nova tambem daria
        `recusado`, e o caso passava com as duas implementacoes.
        """
        ramo = self._ramo_reparado("claude/reparado-abc123")
        self.assertIs(base.e_antepassado(self.raiz, self.publica, ramo), True)
        self.assertIs(base.e_antepassado(self.raiz, self.antiga, ramo), False)

    def test_a_ultima_entrada_do_reflog_responde_ao_presente(self) -> None:
        """A outra forma de errar a mesma pergunta: ler a entrada **mais recente**.

        O ramo reparado trabalhou depois da reparacao, pelo que a ultima entrada
        fala do *commit* de hoje e nao da origem. Fica medido aqui para que a
        escolha da **primeira** entrada em `origem_do_ramo` seja uma decisao com
        prova, e nao a ordem em que alguem calhou de escrever o `readline`.
        """
        ramo = self._ramo_reparado("claude/reparado-abc123")
        caminho = base.caminho_do_reflog(self.raiz, ramo)
        assert caminho is not None
        linhas = caminho.read_text(encoding="utf-8").splitlines()
        self.assertGreater(len(linhas), 1, "a fixture tem de ter mais de uma entrada")

        primeira = base.ler_entrada(linhas[0])
        ultima = base.ler_entrada(linhas[-1])
        assert primeira is not None and ultima is not None
        self.assertEqual(primeira.velho, self.antiga)
        self.assertEqual(ultima.velho, self.publica)
        # As duas leituras, com respostas opostas.
        self.assertIs(
            base.e_antepassado(self.raiz, primeira.velho, base.REFERENCIA_PADRAO), False
        )
        self.assertIs(
            base.e_antepassado(self.raiz, ultima.velho, base.REFERENCIA_PADRAO), True
        )

    def test_ler_a_coluna_nova_daria_conforme_e_e_o_falso_negativo(self) -> None:
        """O defeito medido, reproduzido: a coluna **nova** responde «conforme».

        Nao e um teste do `base.py` — e a prova de que a escolha do `base.py` nao
        e arbitraria. Sem este caso, «ler a coluna antiga» era uma preferencia de
        estilo.
        """
        ramo = self._ramo_reparado("claude/reparado-abc123")
        caminho = base.caminho_do_reflog(self.raiz, ramo)
        assert caminho is not None
        primeira = caminho.read_text(encoding="utf-8").splitlines()[0]
        entrada = base.ler_entrada(primeira)
        assert entrada is not None

        self.assertEqual(entrada.velho, self.antiga)
        self.assertEqual(entrada.novo, self.publica)
        # A mensagem nomeia a referencia CERTA, numa entrada cuja origem e a
        # errada: decidir pela mensagem repete o defeito por outra via.
        self.assertIn("Reset to", primeira)
        self.assertIn(base.REFERENCIA_PADRAO, primeira)

        # As duas leituras, lado a lado, com respostas opostas.
        self.assertIs(
            base.e_antepassado(self.raiz, entrada.velho, base.REFERENCIA_PADRAO), False
        )
        self.assertIs(
            base.e_antepassado(self.raiz, entrada.novo, base.REFERENCIA_PADRAO), True
        )

    def test_a_entrada_descarta_a_mensagem(self) -> None:
        """A mensagem nao fica guardada: guarda-la convidava a decidir por ela."""
        entrada = base.ler_entrada(
            f"{self.antiga} {self.publica} teste <t@kamba.local> 1793796802 +0100"
            "\tbranch: Reset to refs/remotes/publico/main"
        )
        assert entrada is not None
        self.assertEqual(
            {campo for campo in vars(entrada)}, {"velho", "novo"}
        )


class TestFalhaFechada(ComDuasLinhas):
    """Sem *reflog*, o comando diz que nao sabe. Nunca diz que esta conforme."""

    def test_sem_reflog_diz_que_nao_sabe(self) -> None:
        """Sem *reflog* **e** com a ponta a tocar a linha certa: nao se sabe.

        O ramo e cortado da linha **certa**, de proposito. Um ramo sem *reflog*
        na linha **errada** e `RECUSADO` pela ponta, que e um sinal conclusivo —
        ver `TestOSinalDaPonta`. O «nao sei» e para quando nenhum dos dois sinais
        responde, e e este o estado.
        """
        ramo = self._ramo_sem_reflog("claude/sem-reflog-abc123", self.publica)
        caminho = base.caminho_do_reflog(self.raiz, ramo)
        assert caminho is not None
        self.assertFalse(caminho.is_file(), "a fixture tem de deixar o ramo sem log")

        veredicto = self._avaliar(ramo)
        self.assertEqual(veredicto.estado, base.DESCONHECIDO)
        self.assertIsNone(veredicto.origem)
        self.assertNotEqual(veredicto.codigo, 0)
        self.assertEqual(veredicto.codigo, 2)

    def test_sem_reflog_o_cli_sai_nao_zero_e_nao_diz_conforme(self) -> None:
        ramo = self._ramo_sem_reflog("claude/sem-reflog-abc123", self.publica)
        saida, erro = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            codigo = cli.main(["--root", str(self.raiz), "base", ramo])
        self.assertEqual(codigo, 2)
        self.assertIn("NAO SE SABE", erro.getvalue())
        self.assertNotIn("conforme", erro.getvalue())
        self.assertEqual(saida.getvalue(), "")

    def test_o_nao_sei_nao_manda_reparar_e_o_recusado_manda(self) -> None:
        """Os dois estados nao-conformes imprimem textos diferentes.

        Dizer «nao sei» e a seguir mandar reparar era contradizer-se na linha
        seguinte, e deixava os dois estados distintos so na etiqueta.
        """
        desconhecido = self._ramo_sem_reflog("claude/sem-reflog-abc123", self.publica)
        recusado = self._ramo_criado_em("claude/errado-abc123", self.antiga)

        textos = {}
        for ramo in (desconhecido, recusado):
            erro = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(erro):
                cli.main(["--root", str(self.raiz), "base", ramo])
            textos[ramo] = erro.getvalue()

        self.assertIn("Como reparar", textos[recusado])
        self.assertNotIn("Como reparar", textos[desconhecido])
        self.assertIn("Como descobrir", textos[desconhecido])

    def test_referencia_que_nao_existe_diz_que_nao_sabe(self) -> None:
        """Quem nunca fez o `fetch` com *refspec* nao tem a referencia local.

        O `merge-base --is-ancestor` sai 128, que nao e 0 nem 1. Tratar 128 como
        «nao e antepassado» dava a resposta certa por acidente; tratar como
        «e antepassado» dava um verde falso. Nenhuma das duas e uma medicao.
        """
        ramo = self._ramo_criado_em("feature/KAM-180-certo", self.publica)
        veredicto = base.avaliar(
            self.raiz, ramo, "refs/remotes/inexistente/main"
        )
        self.assertEqual(veredicto.estado, base.DESCONHECIDO)
        self.assertIn("git fetch publico main:", veredicto.razao)

    def test_reflog_ilegivel_nao_passa_por_conforme(self) -> None:
        ramo = self._ramo_criado_em("feature/KAM-180-certo", self.publica)
        caminho = base.caminho_do_reflog(self.raiz, ramo)
        assert caminho is not None
        caminho.write_text("isto nao e uma entrada de reflog\n", encoding="utf-8")
        self.assertEqual(self._avaliar(ramo).estado, base.DESCONHECIDO)

    def test_head_solto_nao_passa_por_conforme(self) -> None:
        _git(self.raiz, "checkout", "--quiet", "--detach", self.publica)
        self.assertIsNone(base.ramo_actual(self.raiz))
        veredicto = base.avaliar(self.raiz)
        self.assertEqual(veredicto.estado, base.DESCONHECIDO)
        self.assertIsNone(veredicto.ramo)


class TestDentroDeUmWorktree(ComDuasLinhas):
    """A forma em que o defeito vive: um *worktree*, nao o *checkout* principal.

    Num *worktree* o `--git-dir` e `.git/worktrees/<nome>` e o `--git-common-dir`
    e o `.git` de cima; os *logs* dos ramos vivem **no comum**. Procura-los no do
    *worktree* nao encontrava ficheiro nenhum e o instrumento respondia
    `DESCONHECIDO` em todo o lado — um falso «nao sei», que cala o instrumento
    exactamente onde ele devia morder. Uma bateria que so medisse o *checkout*
    principal nao via esta diferenca, porque ali os dois directorios coincidem.
    """

    def _worktree(self, nome: str, ramo: str, ponto: str) -> Path:
        caminho = Path(self.directorio.name) / nome
        _git(self.raiz, "worktree", "add", "--quiet", str(caminho), "-b", ramo, ponto)
        return caminho

    def test_worktree_cortado_da_linha_certa_sai_conforme(self) -> None:
        arvore = self._worktree("wt-certo", "feature/KAM-180-certo", self.publica)
        veredicto = base.avaliar(arvore)
        self.assertEqual(veredicto.estado, base.CONFORME)
        self.assertEqual(veredicto.ramo, "feature/KAM-180-certo")

    def test_worktree_cortado_da_linha_antiga_sai_recusado(self) -> None:
        """O defeito real, reconstruido: o *worktree* nasce na linha errada."""
        arvore = self._worktree("wt-errado", "claude/gerado-abc123", self.antiga)
        veredicto = base.avaliar(arvore)
        self.assertEqual(veredicto.estado, base.RECUSADO)
        self.assertEqual(veredicto.origem, self.antiga)

    def test_o_reflog_le_se_do_directorio_comum_e_nao_do_worktree(self) -> None:
        arvore = self._worktree("wt-certo", "feature/KAM-180-certo", self.publica)
        proprio = _git(arvore, "rev-parse", "--git-dir")
        comum = _git(arvore, "rev-parse", "--git-common-dir")
        self.assertNotEqual(
            Path(proprio).resolve(),
            Path(comum).resolve(),
            "a fixture tem de ser um worktree a serio",
        )
        caminho = base.caminho_do_reflog(arvore, "feature/KAM-180-certo")
        assert caminho is not None
        self.assertTrue(caminho.is_file())
        self.assertNotIn("worktrees", str(caminho))


class TestOSinalDaPonta(ComDuasLinhas):
    """A recusa conclusiva que **nao** precisa de *reflog* — achado da revisão.

    Os 37 ramos `claude/*` parados em `f344990` nao tem ficheiro de *log* nenhum,
    porque a aplicacao cria o ramo sem o escrever. Sem este sinal o instrumento
    respondia «nao sei» a **37 de 37** dos ramos em que o defeito esta vivo, e
    «recusado» so aos que alguem ja tinha reparado — isto e, respondia aos que
    nao precisavam de resposta.
    """

    def test_ramo_sem_reflog_na_linha_errada_e_recusado_pela_ponta(self) -> None:
        ramo = self._ramo_sem_reflog("claude/gerado-abc123", self.antiga)
        caminho = base.caminho_do_reflog(self.raiz, ramo)
        assert caminho is not None
        self.assertFalse(caminho.is_file(), "a fixture tem de deixar o ramo sem log")

        veredicto = self._avaliar(ramo)
        self.assertEqual(veredicto.estado, base.RECUSADO)
        self.assertEqual(veredicto.codigo, 1)
        self.assertIn("antepassado comum", veredicto.razao)

    def test_a_ponta_distingue_sem_antepassado_comum_de_apenas_a_frente(self) -> None:
        """A premissa do sinal, e porque e que `e_antepassado` nao servia aqui.

        Um ramo com trabalho por cima da linha certa **nao** e antepassado da
        referencia — esta a frente dela — pelo que `e_antepassado` responde
        `False` para o ramo bom e para o cortado, e nao discrimina nada. O que
        discrimina e **nao ter antepassado comum nenhum**.
        """
        bom = self._ramo_criado_em("feature/KAM-180-certo", self.publica)
        _git(self.raiz, "checkout", "--quiet", bom)
        _commit(self.raiz, "frente.txt", "feat(KAM-180): trabalho por cima")
        ponta_boa = _git(self.raiz, "rev-parse", bom)

        # As duas pontas respondem `False` ao `e_antepassado`...
        self.assertIs(
            base.e_antepassado(self.raiz, ponta_boa, base.REFERENCIA_PADRAO), False
        )
        self.assertIs(
            base.e_antepassado(self.raiz, self.antiga, base.REFERENCIA_PADRAO), False
        )
        # ...e **so** o antepassado comum as separa.
        self.assertIs(
            base.tem_antepassado_comum(self.raiz, ponta_boa, base.REFERENCIA_PADRAO),
            True,
        )
        self.assertIs(
            base.tem_antepassado_comum(self.raiz, self.antiga, base.REFERENCIA_PADRAO),
            False,
        )

    def test_o_ramo_bom_com_trabalho_por_cima_continua_conforme(self) -> None:
        """O controlo do sinal da ponta: nao pode recusar quem esta a frente."""
        ramo = self._ramo_criado_em("feature/KAM-180-certo", self.publica)
        _git(self.raiz, "checkout", "--quiet", ramo)
        _commit(self.raiz, "frente.txt", "feat(KAM-180): trabalho por cima")
        self.assertEqual(self._avaliar(ramo).estado, base.CONFORME)

    def test_o_reflog_ainda_decide_o_que_a_ponta_nao_ve(self) -> None:
        """O ramo reparado tem ponta boa, pelo que **so** o reflog o apanha.

        É a razão de os dois sinais serem necessários: este caso fica verde se
        alguém tirar a leitura do *reflog* por achar que a ponta já basta.
        """
        ramo = self._ramo_reparado("claude/reparado-abc123")
        ponta = _git(self.raiz, "rev-parse", ramo)
        self.assertIs(
            base.tem_antepassado_comum(self.raiz, ponta, base.REFERENCIA_PADRAO), True
        )
        self.assertEqual(self._avaliar(ramo).estado, base.RECUSADO)


class TestAReferenciaPorExtenso(ComDuasLinhas):
    """Um ramo **local** chamado `publico/main` sequestra o nome curto.

    `base.py` escreve isto como premissa de desenho — e a revisão adversarial
    mostrou que estava defendida **por comentário**, que é o que o critério 3
    proíbe. Construído, o veredicto **inverte-se nos dois sentidos**: o ramo bom
    sai recusado e o cortado sai conforme.
    """

    def setUp(self) -> None:
        super().setUp()
        # O ramo local que tem o nome da referencia curta, na linha ERRADA.
        _git(self.raiz, "branch", "publico/main", self.antiga)

    def test_o_nome_curto_resolve_para_a_linha_errada(self) -> None:
        """A premissa: sem isto, os casos abaixo nao mediriam nada."""
        self.assertEqual(_git(self.raiz, "rev-parse", "publico/main"), self.antiga)
        self.assertEqual(
            _git(self.raiz, "rev-parse", base.REFERENCIA_PADRAO), self.publica
        )

    def test_a_referencia_por_extenso_da_as_respostas_certas(self) -> None:
        for ramo, commit, esperado in (
            ("feature/KAM-180-certo", self.publica, base.CONFORME),
            ("claude/errado-abc123", self.antiga, base.RECUSADO),
        ):
            with self.subTest(ramo=ramo):
                self._ramo_criado_em(ramo, commit)
                self.assertEqual(
                    base.avaliar(self.raiz, ramo, base.REFERENCIA_PADRAO).estado,
                    esperado,
                )

    def test_o_nome_curto_inverteria_as_duas_respostas(self) -> None:
        """O defeito, medido: e por isso que a constante leva `refs/remotes/`."""
        for ramo, commit, invertido in (
            ("feature/KAM-180-certo", self.publica, base.RECUSADO),
            ("claude/errado-abc123", self.antiga, base.CONFORME),
        ):
            with self.subTest(ramo=ramo):
                self._ramo_criado_em(ramo, commit)
                self.assertEqual(
                    base.avaliar(self.raiz, ramo, "publico/main").estado, invertido
                )

    def test_a_constante_leva_o_prefixo(self) -> None:
        self.assertTrue(base.REFERENCIA_PADRAO.startswith("refs/remotes/"))


class TestReflogPodado(ComDuasLinhas):
    """Um *reflog* podado **em parte** dava `conforme` — achado da revisão.

    O `gc.reflogExpireUnreachable` são **30 dias** por omissão, e as entradas que
    apontam para a linha antiga são inalcançáveis a partir da certa: são as
    primeiras a cair. Num ramo **reparado** sobram as entradas posteriores, cuja
    coluna antiga é o *commit* de **depois** da reparação — e a resposta saía
    `conforme`, que é o mesmo falso negativo do `reflog show` por outra via.
    """

    def _podar_a_primeira(self, ramo: str) -> None:
        caminho = base.caminho_do_reflog(self.raiz, ramo)
        assert caminho is not None
        linhas = caminho.read_text(encoding="utf-8").splitlines(keepends=True)
        self.assertGreater(len(linhas), 1, "a fixture tem de ter mais de uma entrada")
        caminho.write_text("".join(linhas[1:]), encoding="utf-8")

    def test_reparado_com_a_primeira_entrada_podada_nao_sai_conforme(self) -> None:
        ramo = self._ramo_reparado("claude/reparado-abc123")
        self.assertEqual(self._avaliar(ramo).estado, base.RECUSADO)
        self._podar_a_primeira(ramo)
        veredicto = self._avaliar(ramo)
        self.assertNotEqual(veredicto.estado, base.CONFORME)
        self.assertEqual(veredicto.estado, base.DESCONHECIDO)
        self.assertIn("nao e de criacao", veredicto.razao)

    def test_o_conforme_exige_entrada_de_criacao(self) -> None:
        """A regra, nas duas direcções, para que não seja um acaso do caso acima."""
        criado = self._ramo_criado_em("feature/KAM-180-certo", self.publica)
        origem, _ = base.origem_do_ramo(self.raiz, criado)
        assert origem is not None
        self.assertTrue(origem.de_criacao)
        self.assertEqual(self._avaliar(criado).estado, base.CONFORME)

        # O mesmo commit de origem, mas sem entrada de criacao: nao fecha verde.
        sem_criacao = "claude/sem-criacao-abc123"
        self._ramo_sem_reflog(sem_criacao, self.publica)
        _git(self.raiz, "checkout", "--quiet", sem_criacao)
        _commit(self.raiz, "t.txt", "feat(KAM-180): trabalho sem entrada de criacao")
        origem, _ = base.origem_do_ramo(self.raiz, sem_criacao)
        assert origem is not None
        self.assertFalse(origem.de_criacao)
        self.assertEqual(origem.commit, self.publica)
        self.assertEqual(self._avaliar(sem_criacao).estado, base.DESCONHECIDO)

    def test_reflog_esvaziado_por_completo_continua_a_cair_em_nao_sei(self) -> None:
        ramo = self._ramo_criado_em("feature/KAM-180-certo", self.publica)
        caminho = base.caminho_do_reflog(self.raiz, ramo)
        assert caminho is not None
        caminho.write_text("", encoding="utf-8")
        self.assertEqual(self._avaliar(ramo).estado, base.DESCONHECIDO)


class TestArmadilhaDoMergeBase(ComDuasLinhas):
    """Armadilha 1: o `merge-base` sai 1 **sem saida**, e o codigo e o unico sinal."""

    def test_o_merge_base_sai_um_sem_saida_entre_as_duas_linhas(self) -> None:
        resultado = _bruto(self.raiz, "merge-base", self.antiga, self.publica)
        self.assertEqual(resultado.returncode, 1)
        self.assertEqual(resultado.stdout.strip(), "")
        self.assertEqual(resultado.stderr.strip(), "")

    def test_o_is_ancestor_tambem_nao_imprime_nada_em_nenhuma_resposta(self) -> None:
        """A razao de forma: com `--is-ancestor` o codigo de saida nao e uma das
        fontes de verdade — e a unica. Um *script* que capture a saida fica com a
        string vazia nas duas respostas e nao distingue nada."""
        for commit, esperado in ((self.publica, 0), (self.antiga, 1)):
            with self.subTest(commit=commit[:7]):
                resultado = _bruto(
                    self.raiz,
                    "merge-base",
                    "--is-ancestor",
                    commit,
                    base.REFERENCIA_PADRAO,
                )
                self.assertEqual(resultado.returncode, esperado)
                self.assertEqual(resultado.stdout, "")

    def test_o_comando_le_o_codigo_de_saida(self) -> None:
        self.assertIs(
            base.e_antepassado(self.raiz, self.antiga, base.REFERENCIA_PADRAO), False
        )
        self.assertIs(
            base.e_antepassado(self.raiz, self.publica, base.REFERENCIA_PADRAO), True
        )
        self.assertIsNone(
            base.e_antepassado(self.raiz, "nao-e-um-commit", base.REFERENCIA_PADRAO)
        )

    def test_a_saida_vazia_nao_se_le_como_zero_diferencas(self) -> None:
        """O defeito, reproduzido: capturar a saida e nao ler o codigo.

        A variavel fica vazia nas duas respostas — e um ramo da linha antiga
        ficava indistinguivel de um ramo que nao tem nada a mais do que a base.
        """
        capturada = {
            commit[:7]: _bruto(
                self.raiz, "merge-base", commit, self.publica
            ).stdout.strip()
            for commit in (self.antiga, self.publica)
        }
        # A da linha antiga e vazia; a da linha certa nao. Mas quem captura **so**
        # a saida nao sabe que a vazia significa «nao ha relacao».
        self.assertEqual(capturada[self.antiga[:7]], "")
        self.assertIs(
            base.e_antepassado(self.raiz, self.antiga, base.REFERENCIA_PADRAO), False
        )

    def test_a_variavel_sem_aspas_colapsa_o_diff_e_com_aspas_falha_alto(self) -> None:
        """A forma do defeito, medida: `git diff "" <ramo>` falha; sem aspas, nao.

        Com a variavel vazia **e sem aspas**, o `git diff $BASE $ramo` colapsa em
        `git diff $ramo` — um comando legitimo, que devolve uma resposta plausivel
        e se le como «este ramo nao tem nada a mais do que a base». Foi assim que
        se estiveram a apagar *worktrees* cujo trabalho a linha certa nao contem.
        **Com aspas falha alto**, e e por isso que a forma com aspas e a que nao
        reproduz o defeito.
        """
        vazia = _bruto(self.raiz, "merge-base", self.antiga, self.publica).stdout.strip()
        self.assertEqual(vazia, "")

        # Com aspas: o argumento vazio chega ao git, e o git recusa.
        com_aspas = _bruto(self.raiz, "diff", vazia, self.antiga)
        self.assertNotEqual(com_aspas.returncode, 0)
        self.assertIn("ambiguous argument", com_aspas.stderr)

        # Sem aspas: o argumento desaparece, e o git responde a outra pergunta
        # com codigo 0 — uma resposta plausivel, que e o que torna isto uma
        # armadilha e nao um erro.
        sem_aspas = _bruto(self.raiz, "diff", self.antiga)
        self.assertEqual(sem_aspas.returncode, 0)


class TestArmadilhaDoRevList(ComDuasLinhas):
    """Armadilha 2: o `rev-list` responde, e a resposta nao quer dizer o que parece."""

    def test_o_rev_list_devolve_um_par_plausivel_entre_linhas_sem_relacao(self) -> None:
        resultado = _bruto(
            self.raiz,
            "rev-list",
            "--left-right",
            "--count",
            f"{self.antiga}...{self.publica}",
        )
        self.assertEqual(resultado.returncode, 0, "o rev-list responde, e e o problema")
        esquerda, direita = resultado.stdout.split()
        self.assertGreater(int(esquerda), 0)
        self.assertGreater(int(direita), 0)

    def test_o_diff_com_tres_pontos_e_que_diz_a_verdade(self) -> None:
        resultado = _bruto(self.raiz, "diff", f"{self.antiga}...{self.publica}")
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("no merge base", resultado.stderr)

    def test_o_comando_nao_decide_pelo_par(self) -> None:
        """O par e plausivel nos dois sentidos, e o veredicto nao o segue."""
        for ramo, commit, esperado in (
            ("claude/errado-abc123", self.antiga, base.RECUSADO),
            ("feature/KAM-180-certo", self.publica, base.CONFORME),
        ):
            with self.subTest(ramo=ramo):
                self._ramo_criado_em(ramo, commit)
                self.assertEqual(self._avaliar(ramo).estado, esperado)


class TestNoRepositorioReal(unittest.TestCase):
    """Os casos que medem **este** repositorio, e que o arreio de mutacao salta.

    A copia que o `mutacoes_base.py` faz leva `tools/` e mais nada: nao tem
    arvore de git, pelo que estes nao tem o que medir. Ficam marcados com a
    condicao escrita — e nao excluidos por nome, que era como um caso que passasse
    a nao correr no repositorio passava calado.
    """

    @unittest.skipUnless(
        (RAIZ / ".git").exists(), "sem arvore de git: a copia do arreio nao a leva"
    )
    def test_o_ramo_actual_deste_worktree_e_conforme(self) -> None:
        """A direccao positiva, medida no repositorio e nao numa *fixture*.

        Este *worktree* nasceu em `f344990` como todos os outros, e foi reparado
        com `git checkout -B fix/KAM-180-… refs/remotes/publico/main` antes da
        primeira edicao. Se este caso ficar vermelho num *worktree* novo, o
        defeito esta a acontecer outra vez — que e precisamente o que o
        instrumento existe para dizer.
        """
        veredicto = base.avaliar(RAIZ)
        # **Exige `CONFORME` e nada mais.** Aceitar tambem `DESCONHECIDO`
        # deixava-o verde com uma implementacao que respondesse sempre «nao
        # sei», pelo que nao distinguia um instrumento que funciona de um que
        # esta calado — achado da revisao adversarial. Quem corra a bateria num
        # *worktree* por reparar ve isto vermelho, e **e** o alarme.
        self.assertEqual(
            veredicto.estado,
            base.CONFORME,
            f"a base deste ramo nao e conforme ({veredicto.estado}): "
            f"{veredicto.razao}",
        )

    @unittest.skipUnless(
        (RAIZ / ".git").exists(), "sem arvore de git: a copia do arreio nao a leva"
    )
    def test_o_caminho_do_reflog_sai_do_directorio_comum(self) -> None:
        """Num *worktree*, os *logs* dos ramos vivem no `--git-common-dir`.

        Procura-los no `--git-dir` — que num *worktree* e
        `.git/worktrees/<nome>` — nao encontrava ficheiro nenhum, e **todo** o
        repositorio respondia `DESCONHECIDO`: um falso «nao sei» que calava o
        instrumento onde ele devia morder.
        """
        caminho = base.caminho_do_reflog(RAIZ, "main")
        assert caminho is not None
        self.assertEqual(caminho.parts[-4:], ("logs", "refs", "heads", "main"))
        comum = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=RAIZ,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertNotIn("worktrees", str(caminho))
        self.assertTrue(str(caminho).startswith(str(Path(comum))) or not Path(comum).is_absolute())


if __name__ == "__main__":
    unittest.main()
