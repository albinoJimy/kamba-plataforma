"""A segunda passagem do gate 9: os blobs que o intervalo acrescenta (KAM-131).

O teste central e o do padrao A->B — um segredo posto num commit e retirado no
seguinte —, que e o cenario que a passagem da arvore nao ve e com que o proprio
`docs/ci.md` justifica o *pre-commit*.

Os valores de forma real nao estao em linha neste ficheiro, pela mesma razao que
em `test_scanner.py`: leem-se da pasta do canario, a unica area onde um segredo
com forma real e permitido.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scan_secrets.cli import ficheiros_seguidos, main
from scan_secrets.historia import (
    EXIGEM_COMMITS,
    SEM_COMMIT,
    SEM_INTERVALO,
    decidir_intervalo,
    exigir_commits,
    varrer_intervalo,
)
from scan_secrets.scanner import ConfiguracaoInvalida, Permissoes, varrer_ficheiros

ROOT = Path(__file__).resolve().parents[3]
CANARIO = Path(__file__).resolve().parent / "fixtures" / "canario"

#: Caminho dentro da pasta do canario, que `ci/secrets-allow.yaml` permite.
NA_AREA = "tools/scan_secrets/tests/fixtures/canario/segredos.txt"
#: Caminho sem area nenhuma, que ordena **antes** do caminho do canario.
FORA_DA_AREA = "services/gwy/src/config.ts"
#: Caminho sem area nenhuma, que ordena **depois** do caminho do canario.
#:
#: Existe porque a bateria so tinha o de cima, e isso fazia os testes das areas
#: passarem por acidente da ordem alfabetica: uma implementacao que confrontasse
#: **o primeiro** caminho do blob em vez de todos ficava verde nos dois sentidos
#: com `services/…`, e vermelha num deles com `zz/…`. Achado A6 da revisao.
FORA_DA_AREA_NO_FIM = "zz-servicos/config.ts"


def _caso(nome: str) -> str:
    """Uma linha de `fixtures/canario/casos.txt`, por nome do padrao."""
    for linha in (CANARIO / "casos.txt").read_text(encoding="utf-8").splitlines():
        if linha.startswith("#") or "|" not in linha:
            continue
        chave, _, conteudo = linha.partition("|")
        if chave.strip() == nome:
            return conteudo
    raise AssertionError(f"o caso {nome!r} nao existe no canario")


#: Uma chave de API com prefixo publicado: classe `chave_api`, que nenhuma area
#: permite fora da pasta do canario e que os placeholders nao dispensam.
SEGREDO = _caso("openai") + "\n"
#: O valor em si, para se verificar que **nao** aparece no relatorio.
VALOR = SEGREDO.strip().partition("=")[2]


#: A identidade e a assinatura passam pelo ambiente, e o ramo pela unica opcao
#: do `init`. Sao quatro invocacoes do `git` por teste em vez de oito — e numa
#: maquina Windows cada invocacao custa perto de um terco de segundo, o que
#: fazia desta bateria a mais lenta de `tools/`.
RAMO = "tronco"
AMBIENTE_GIT = {
    "GIT_AUTHOR_NAME": "KAMBA CI",
    "GIT_AUTHOR_EMAIL": "ci@kamba.invalid",
    "GIT_COMMITTER_NAME": "KAMBA CI",
    "GIT_COMMITTER_EMAIL": "ci@kamba.invalid",
    "GIT_AUTHOR_DATE": "2026-10-12T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-10-12T00:00:00+00:00",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


class Repositorio:
    """Um repositorio git de uma linha, construido no teste."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz
        self.ramo = RAMO
        raiz.mkdir(parents=True, exist_ok=True)
        self.git("-c", f"init.defaultBranch={RAMO}", "init", "-q")
        # A configuracao do gate fica **fora** do git: assim nunca entra em
        # intervalo nenhum e os numeros de blobs de cada teste sao os dos
        # ficheiros que o teste escreve.
        (raiz / "ci").mkdir()
        shutil.copy(ROOT / "ci" / "secrets-allow.yaml", raiz / "ci" / "secrets-allow.yaml")
        self.base = self.comitar("base", {"leia-me.txt": "base\n"})

    @classmethod
    def copia_do_prototipo(cls, destino: Path) -> "Repositorio":
        """Uma copia do repositorio-modelo, sem invocar o `git`.

        O `git init` e o commit de base sao quatro processos, e num `git` de
        Windows custam perto de quatro segundos — vezes o numero de testes desta
        bateria. Copiar a pasta e uma operacao de ficheiros e nao de processos.
        """
        shutil.copytree(_PROTOTIPO, destino)
        repositorio = cls.__new__(cls)
        repositorio.raiz = destino
        repositorio.ramo = RAMO
        repositorio.base = _BASE
        return repositorio

    def git(self, *argumentos: str, entrada: bytes | None = None) -> str:
        resultado = subprocess.run(
            ["git", *argumentos],
            cwd=self.raiz,
            input=entrada,
            capture_output=True,
            check=True,
            env={**os.environ, **AMBIENTE_GIT},
        )
        return resultado.stdout.decode("utf-8", "replace")

    def escrever(self, caminho: str, conteudo: str) -> None:
        alvo = self.raiz / caminho
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(conteudo, encoding="utf-8", newline="\n")

    def comitar(
        self,
        mensagem: str,
        ficheiros: dict[str, str] | None = None,
        apagar: list[str] | None = None,
    ) -> str:
        for caminho, conteudo in (ficheiros or {}).items():
            self.escrever(caminho, conteudo)
            self.git("add", "--", caminho)
        for caminho in apagar or []:
            self.git("rm", "-q", "--", caminho)
        self.git("commit", "-q", "-m", mensagem)
        return self.git("rev-parse", "HEAD").strip()

    def comitar_em_serie(self, quantos: int, modelo: str) -> None:
        """`quantos` commits, cada um com um ficheiro novo, numa so invocacao.

        Por `git fast-import` e nao por `quantos` chamadas ao `git commit`: o
        criterio de aceitacao fala de um PR de 40 commits, e 40 commits a tres
        invocacoes cada levavam mais de um minuto so nesta bateria.
        """
        ramo = f"refs/heads/{self.ramo}".encode()
        ponta = self.git("rev-parse", self.ramo).strip().encode()
        partes: list[bytes] = []
        for numero in range(quantos):
            conteudo = (modelo % numero).encode()
            mensagem = f"c{numero}".encode()
            partes += [
                b"commit " + ramo + b"\n",
                b"committer KAMBA CI <ci@kamba.invalid> 1760227200 +0000\n",
                b"data " + str(len(mensagem)).encode() + b"\n",
                mensagem + b"\n",
            ]
            if numero == 0:
                # So o primeiro leva `from`, e pelo SHA: o ramo ainda nao e
                # conhecido do `fast-import`, e `from refs/heads/<ramo>` seria
                # «criar um ramo a partir de si mesmo». Os seguintes encadeiam-se
                # na ponta que o proprio `fast-import` ja construiu.
                partes.append(b"from " + ponta + b"\n")
            partes += [
                b"M 100644 inline services/f" + str(numero).encode() + b".ts\n",
                b"data " + str(len(conteudo)).encode() + b"\n",
                conteudo + b"\n",
            ]
        self.git("fast-import", "--quiet", entrada=b"".join(partes))
        self.git("reset", "-q", "--hard", self.ramo)


#: O repositorio-modelo do modulo: um `git init` e um commit de base, uma vez.
_PROTOTIPO: Path
_BASE: str
_PASTA_DO_PROTOTIPO: str


def setUpModule() -> None:
    global _PROTOTIPO, _BASE, _PASTA_DO_PROTOTIPO
    _PASTA_DO_PROTOTIPO = tempfile.mkdtemp(prefix="kamba-gate9-")
    _PROTOTIPO = Path(_PASTA_DO_PROTOTIPO) / "modelo"
    _BASE = Repositorio(_PROTOTIPO).base


def tearDownModule() -> None:
    # `ignore_errors`: o `git` de Windows deixa objectos so de leitura, e uma
    # limpeza que falhe nao pode vermelhar a bateria.
    shutil.rmtree(_PASTA_DO_PROTOTIPO, ignore_errors=True)


class ComRepositorio(unittest.TestCase):
    def setUp(self) -> None:
        pasta = tempfile.mkdtemp(prefix="kamba-gate9-")
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        self.repo = Repositorio.copia_do_prototipo(Path(pasta) / "repo")
        self.permissoes = Permissoes.ler(self.repo.raiz)

    def varrer(self, base: str, head: str = "HEAD"):
        return varrer_intervalo(self.repo.raiz, base, head, self.permissoes)

    def caminhos(self, resultado) -> set[str]:
        return {achado.achado.ficheiro for achado in resultado.achados}


class TestPadraoAB(ComRepositorio):
    """O cenario que a passagem da arvore nao ve."""

    def test_segredo_posto_em_a_e_retirado_em_b_e_achado(self) -> None:
        base = self.repo.base
        self.repo.comitar("A: entra o segredo", {FORA_DA_AREA: SEGREDO})
        self.repo.comitar("B: sai o segredo", apagar=[FORA_DA_AREA])

        resultado = self.varrer(base)
        self.assertEqual(resultado.commits, 2)
        self.assertTrue(resultado.achados, "o blob do commit A tem de ser varrido")
        self.assertEqual(self.caminhos(resultado), {FORA_DA_AREA})

    def test_a_arvore_final_do_mesmo_ramo_esta_limpa(self) -> None:
        """As duas passagens, no mesmo estado: a arvore verde, a historia vermelha.

        E o «antes» da demonstracao do ticket, provado por execucao: sem a
        segunda passagem, este ramo passa o gate 9.
        """
        base = self.repo.base
        self.repo.comitar("A: entra o segredo", {FORA_DA_AREA: SEGREDO})
        self.repo.comitar("B: sai o segredo", apagar=[FORA_DA_AREA])

        da_arvore = varrer_ficheiros(
            ficheiros_seguidos(self.repo.raiz), self.repo.raiz, self.permissoes
        )
        self.assertEqual(da_arvore, [], "a arvore final nao tem o segredo — e o problema")
        self.assertTrue(self.varrer(base).achados)

    def test_o_segredo_na_arvore_e_achado_pelas_duas_passagens(self) -> None:
        """Nenhuma passagem substitui a outra, e nenhuma reporta duas vezes."""
        base = self.repo.base
        self.repo.comitar("A: entra o segredo e fica", {FORA_DA_AREA: SEGREDO})

        da_arvore = varrer_ficheiros(
            ficheiros_seguidos(self.repo.raiz), self.repo.raiz, self.permissoes
        )
        da_historia = self.varrer(base)
        self.assertTrue(da_arvore)
        self.assertTrue(da_historia.achados)
        # Uma vez por caminho em cada passagem: o mesmo padrao na mesma linha
        # nao aparece duas vezes dentro da mesma passagem.
        self.assertEqual(
            len({(a.ficheiro, a.linha, a.padrao) for a in da_arvore}), len(da_arvore)
        )
        self.assertEqual(
            len(
                {
                    (a.achado.ficheiro, a.achado.linha, a.achado.padrao, a.blob)
                    for a in da_historia.achados
                }
            ),
            len(da_historia.achados),
        )


class TestConjuntoDeBlobs(ComRepositorio):
    def test_o_que_e_anterior_a_base_nao_se_varre(self) -> None:
        """O intervalo e o do PR, nao o `main` inteiro."""
        self.repo.comitar("antigo, ja em main", {"services/velho.ts": SEGREDO})
        base = self.repo.git("rev-parse", "HEAD").strip()
        self.repo.comitar("novo", {"services/novo.ts": "export const n = 1;\n"})

        resultado = self.varrer(base)
        self.assertEqual(resultado.commits, 1)
        self.assertEqual(resultado.blobs_varridos, 1)
        self.assertEqual(resultado.achados, ())

    def test_sem_commits_novos_nao_se_varre_nada(self) -> None:
        resultado = self.varrer(self.repo.base, self.repo.base)
        self.assertEqual((resultado.commits, resultado.blobs_varridos), (0, 0))
        self.assertEqual(resultado.achados, ())

    def test_quarenta_commits_varrem_os_quarenta(self) -> None:
        """«um PR de 40 *commits* varre os 40», a letra do criterio 3."""
        base = self.repo.base
        self.repo.comitar_em_serie(40, "export const n%d = 1;\n")
        resultado = self.varrer(base)
        self.assertEqual(resultado.commits, 40)
        self.assertEqual(resultado.blobs_varridos, 40)

    def test_blob_repetido_le_se_uma_vez(self) -> None:
        """A deduplicacao e por SHA de objecto: dois caminhos, uma leitura."""
        base = self.repo.base
        limpo = "export const n = 1;\n"
        self.repo.comitar("A", {"services/um.ts": limpo})
        self.repo.comitar("B", {"services/dois.ts": limpo})

        resultado = self.varrer(base)
        self.assertEqual(resultado.commits, 2)
        self.assertEqual(resultado.blobs_varridos, 1, "o mesmo conteudo e um so blob")
        self.assertEqual(resultado.bytes_varridos, len(limpo.encode()))

    def _evil_merge(self, ficheiros: dict[str, str]) -> str:
        """Um merge que acrescenta conteudo **proprio**, que nenhum pai tem."""
        self.repo.git("checkout", "-q", "-b", "lado")
        self.repo.comitar("lado", {"services/lado.ts": "export const a = 1;\n"})
        self.repo.git("checkout", "-q", self.repo.ramo)
        self.repo.comitar("tronco", {"services/tronco.ts": "export const b = 2;\n"})
        self.repo.git("merge", "-q", "--no-ff", "--no-commit", "lado")
        for caminho, conteudo in ficheiros.items():
            self.repo.escrever(caminho, conteudo)
            self.repo.git("add", "--", caminho)
        self.repo.git("commit", "-q", "-m", "merge com conteudo proprio")
        return self.repo.git("rev-parse", "HEAD").strip()

    def test_blob_que_so_o_merge_introduz_e_varrido(self) -> None:
        """Um *evil merge* nao escapa, e o commit fica atribuido.

        O `-c` no `git log` e o que faz isto: sem ele o `git log --raw` nao
        imprime sequer o cabecalho de um merge, e o blob ficava com o unico
        caminho que o `rev-list --objects` nomeasse.
        """
        base = self.repo.base
        merge = self._evil_merge({"services/proprio.ts": SEGREDO})

        resultado = self.varrer(base)
        self.assertIn("services/proprio.ts", self.caminhos(resultado))
        self.assertEqual(
            {a.commit for a in resultado.achados},
            {merge},
            "o registo combinado do merge tem de dar o commit",
        )

    def test_evil_merge_que_poe_o_mesmo_blob_dentro_e_fora_da_area(self) -> None:
        """A evasao que a revisao adversarial construiu (A1).

        O mesmo blob acrescentado por um merge na pasta do canario **e** fora
        dela, e apagado no commit seguinte. O `rev-list --objects` imprime cada
        objecto **uma vez**, com o caminho em que a travessia o encontrou — e se
        esse caminho for o do canario, a area permite-o. O gate ficava verde pela
        ordem alfabetica da travessia, nao pela politica.
        """
        base = self.repo.base
        canario = "tools/scan_secrets/tests/fixtures/canario/x.txt"
        self._evil_merge({canario: SEGREDO, "ui/config.ts": SEGREDO})
        self.repo.comitar("limpo", apagar=[canario, "ui/config.ts"])

        resultado = self.varrer(base)
        da_arvore = varrer_ficheiros(
            ficheiros_seguidos(self.repo.raiz), self.repo.raiz, self.permissoes
        )
        self.assertEqual(da_arvore, [], "a arvore final esta limpa — e o problema")
        self.assertEqual(
            self.caminhos(resultado),
            {"ui/config.ts"},
            "o caminho fora da area tem de ser achado, e o da area nao",
        )

    def test_blob_que_ja_estava_na_base_e_reposto_por_um_merge(self) -> None:
        """A segunda evasao (A2): nem o `rev-list` nem a travessia por commit.

        O `rev-list --objects` exclui o que e alcancavel da base; o `git log`
        sem `-c` nao ve nada num merge. Um blob que **esteja** na base e que um
        *evil merge* reponha fora da area permitida caia entre os dois.
        """
        self.repo.comitar("ja em main", {NA_AREA: SEGREDO})
        base = self.repo.git("rev-parse", "HEAD").strip()
        self._evil_merge({FORA_DA_AREA: SEGREDO})
        self.repo.comitar("limpo", apagar=[FORA_DA_AREA])

        resultado = self.varrer(base)
        self.assertEqual(self.caminhos(resultado), {FORA_DA_AREA})

    def test_uma_mudanca_de_nome_nao_perde_o_commit(self) -> None:
        """`--no-renames`: um registo `R100` leva dois caminhos e descalibrava a
        leitura — o blob ficava sem commit atribuido, que o criterio 7 exige (A6).
        """
        base = self.repo.base
        self.repo.comitar("A", {"services/antigo.ts": SEGREDO})
        self.repo.git("mv", "services/antigo.ts", "services/novo.ts")
        self.repo.git("commit", "-q", "-m", "B: muda de nome")
        renomear = self.repo.git("rev-parse", "HEAD").strip()

        resultado = self.varrer(base)
        self.assertIn("services/novo.ts", self.caminhos(resultado))
        self.assertNotIn(
            SEM_COMMIT,
            {a.commit for a in resultado.achados},
            "com a deteccao de nomes ligada, o blob perdia a atribuicao a commit",
        )
        self.assertIn(renomear, {a.commit for a in resultado.achados})


class TestAreasPermitidas(ComRepositorio):
    def test_na_pasta_do_canario_e_permitido(self) -> None:
        base = self.repo.base
        self.repo.comitar("canario", {NA_AREA: SEGREDO})
        self.assertEqual(self.varrer(base).achados, ())

    def test_movido_para_fora_da_pasta_do_canario_e_achado(self) -> None:
        """A area aplica-se com o caminho que o blob tinha **nesse** commit.

        O mesmo blob entra na area permitida e sai dela. Deduplicar por SHA e
        aplicar a area de um so caminho daria verde pelo caminho mais
        conveniente — e e esse o defeito que este teste fecha.
        """
        base = self.repo.base
        self.repo.comitar("A: na area", {NA_AREA: SEGREDO})
        self.repo.comitar("B: fora da area", {FORA_DA_AREA: SEGREDO}, apagar=[NA_AREA])

        resultado = self.varrer(base)
        self.assertEqual(resultado.blobs_varridos, 1, "e o mesmo blob")
        self.assertEqual(self.caminhos(resultado), {FORA_DA_AREA})

    def test_movido_para_um_caminho_que_ordena_depois_do_canario(self) -> None:
        """O mesmo que o teste acima, no sentido contrario da ordem alfabetica.

        Sem este, uma implementacao que confrontasse **o primeiro** caminho do
        blob em vez de todos ficava verde (A6): `services/…` ordena antes de
        `tools/…`, e o teste passava por acidente.
        """
        base = self.repo.base
        self.repo.comitar("A: na area", {NA_AREA: SEGREDO})
        self.repo.comitar(
            "B: fora da area", {FORA_DA_AREA_NO_FIM: SEGREDO}, apagar=[NA_AREA]
        )

        resultado = self.varrer(base)
        self.assertEqual(resultado.blobs_varridos, 1, "e o mesmo blob")
        self.assertEqual(self.caminhos(resultado), {FORA_DA_AREA_NO_FIM})

    def test_binario_nao_se_varre_e_diz_se(self) -> None:
        base = self.repo.base
        self.repo.comitar("imagem", {"docs/img/logo.png": SEGREDO})
        resultado = self.varrer(base)
        self.assertEqual(resultado.blobs_varridos, 0)
        self.assertEqual(resultado.saltados_por_extensao, 1)
        self.assertEqual(resultado.achados, ())
        self.assertIn("NAO varrido(s) por extensao de binario", resultado.onde)


class TestContabilidadeHonesta(ComRepositorio):
    """O relatorio nao pode afirmar cobertura que nao houve (A4)."""

    def test_conteudo_que_nao_e_utf8_nao_se_conta_como_varrido(self) -> None:
        base = self.repo.base
        bruto = SEGREDO.encode() + b"\xff"
        alvo = self.repo.raiz / FORA_DA_AREA
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(bruto)
        self.repo.git("add", "--", FORA_DA_AREA)
        self.repo.git("commit", "-q", "-m", "A: segredo num ficheiro que nao e UTF-8")
        self.repo.comitar("B", apagar=[FORA_DA_AREA])

        resultado = self.varrer(base)
        self.assertEqual(resultado.blobs_varridos, 0, "nao se varreu nada")
        self.assertEqual(resultado.bytes_varridos, 0, "nem um byte")
        self.assertEqual(resultado.nao_decifraveis, 1)
        self.assertIn("NAO varrido(s) por nao serem texto UTF-8", resultado.onde)

    def test_os_bytes_contados_sao_os_varridos(self) -> None:
        base = self.repo.base
        conteudo = "export const n = 1;\n"
        self.repo.comitar("A", {"services/um.ts": conteudo})
        resultado = self.varrer(base)
        self.assertEqual(resultado.bytes_varridos, len(conteudo.encode()))
        self.assertEqual((resultado.saltados_por_extensao, resultado.nao_decifraveis), (0, 0))
        self.assertNotIn("NAO varrido", resultado.onde)


class TestIntervaloVazio(unittest.TestCase):
    """Num accionamento que decide um merge, zero commits e erro (A3)."""

    def test_pull_request_com_zero_commits_e_erro(self) -> None:
        for accionamento in sorted(EXIGEM_COMMITS):
            with self.subTest(accionamento=accionamento):
                with self.assertRaises(ConfiguracaoInvalida) as apanhado:
                    exigir_commits(accionamento, 0)
                self.assertIn("zero", str(apanhado.exception).lower())

    def test_com_commits_passa(self) -> None:
        for accionamento in sorted(EXIGEM_COMMITS):
            exigir_commits(accionamento, 1)

    def test_push_com_zero_commits_nao_e_erro(self) -> None:
        """Um `push` pode nao trazer commits novos; um PR nao pode."""
        exigir_commits("push", 0)
        exigir_commits("", 0)


class TestRelatorio(ComRepositorio):
    def test_nao_revela_o_valor_e_diz_o_commit_e_o_caminho(self) -> None:
        base = self.repo.base
        commit_a = self.repo.comitar("A", {FORA_DA_AREA: SEGREDO})
        self.repo.comitar("B", apagar=[FORA_DA_AREA])

        resultado = self.varrer(base)
        self.assertTrue(resultado.achados)
        for achado in resultado.achados:
            linha = str(achado)
            self.assertNotIn(VALOR, linha, "o relatorio nunca imprime o valor")
            self.assertIn(commit_a[:12], linha, "a correccao precisa do commit")
            self.assertIn(FORA_DA_AREA, linha, "e do caminho")
            self.assertIn(achado.blob[:12], linha)

    def test_um_commit_que_nao_e_sha_nao_se_trunca(self) -> None:
        """`SEM_COMMIT[:12]` dava `(sem atrib` no campo que a correccao le (A7)."""
        from scan_secrets.historia import AchadoNaHistoria
        from scan_secrets.scanner import Achado

        achado = AchadoNaHistoria(
            achado=Achado(
                ficheiro="services/x.ts", linha=1, padrao="openai",
                classe="chave_api", razao="r", amostra="sk-p…U2 (56 caracteres)",
            ),
            commit=SEM_COMMIT,
            blob="0" * 40,
        )
        self.assertIn(SEM_COMMIT, str(achado))
        self.assertNotIn("(sem atrib ", str(achado))


class TestFailClosed(ComRepositorio):
    def test_base_que_nao_resolve_e_erro(self) -> None:
        self.repo.comitar("A", {"services/um.ts": "export const n = 1;\n"})
        with self.assertRaises(ConfiguracaoInvalida) as apanhado:
            self.varrer("dead" + "beef" * 9)
        self.assertIn("fetch-depth", str(apanhado.exception))

    def test_head_que_nao_resolve_e_erro(self) -> None:
        with self.assertRaises(ConfiguracaoInvalida):
            self.varrer(self.repo.base, "dead" + "beef" * 9)

    def test_clone_raso_e_erro(self) -> None:
        """Um `fetch-depth` que nao alcance a base falha, nao passa em silencio."""
        self.repo.comitar("A", {"services/um.ts": "export const n = 1;\n"})
        self.repo.comitar("B", {"services/dois.ts": "export const n = 2;\n"})
        with tempfile.TemporaryDirectory() as destino:
            clone = Path(destino) / "raso"
            subprocess.run(
                [
                    "git", "clone", "-q", "--depth", "1",
                    self.repo.raiz.as_uri(), str(clone),
                ],
                check=True,
                capture_output=True,
            )
            with self.assertRaises(ConfiguracaoInvalida) as apanhado:
                varrer_intervalo(clone, "HEAD", "HEAD", self.permissoes)
        self.assertIn("raso", str(apanhado.exception))


class TestModoDeAccionamento(unittest.TestCase):
    """A escolha entre falhar e varrer so a arvore, por accionamento.

    Esta escrita em codigo e nao em YAML de proposito: nao ha *lint* de
    *workflows* neste repositorio, pelo que uma condicao em YAML nao e
    verificavel por teste nenhum.
    """

    def test_pull_request_sem_base_e_vermelho(self) -> None:
        with self.assertRaises(ConfiguracaoInvalida) as apanhado:
            decidir_intervalo("pull_request", "", "cafe" * 10)
        self.assertIn("nao da passagem", str(apanhado.exception))

    def test_pull_request_com_base_a_zeros_e_vermelho(self) -> None:
        with self.assertRaises(ConfiguracaoInvalida):
            decidir_intervalo("pull_request", "0" * 40, "cafe" * 10)

    def test_merge_group_sem_base_e_vermelho(self) -> None:
        with self.assertRaises(ConfiguracaoInvalida):
            decidir_intervalo("merge_group", "", "cafe" * 10)

    def test_accionamento_que_nao_esta_escrito_e_vermelho(self) -> None:
        with self.assertRaises(ConfiguracaoInvalida) as apanhado:
            decidir_intervalo("deployment", "", "cafe" * 10)
        self.assertIn("nao esta escrito", str(apanhado.exception))

    def test_push_com_before_a_zeros_varre_so_a_arvore(self) -> None:
        intervalo = decidir_intervalo("push", "0" * 40, "cafe" * 10)
        self.assertEqual(intervalo.modo, "so-arvore")
        self.assertIn("ramo nasceu", intervalo.razao)

    def test_push_com_before_real_varre_o_intervalo(self) -> None:
        intervalo = decidir_intervalo("push", "a" * 40, "b" * 40)
        self.assertEqual(
            (intervalo.modo, intervalo.base, intervalo.head),
            ("historia", "a" * 40, "b" * 40),
        )

    def test_workflow_dispatch_varre_so_a_arvore(self) -> None:
        self.assertEqual(decidir_intervalo("workflow_dispatch", "", "").modo, "so-arvore")

    def test_execucao_local_varre_so_a_arvore(self) -> None:
        intervalo = decidir_intervalo("", "", "HEAD")
        self.assertEqual(intervalo.modo, "so-arvore")
        self.assertIn("GATE9_BASE", intervalo.razao)

    def test_base_sem_head_e_vermelho(self) -> None:
        with self.assertRaises(ConfiguracaoInvalida):
            decidir_intervalo("pull_request", "a" * 40, "")

    def test_a_tabela_de_accionamentos_nao_cresce_sem_decisao(self) -> None:
        """Um accionamento novo tem de passar por aqui, e nao por omissao."""
        self.assertEqual(
            set(SEM_INTERVALO),
            {
                "pull_request",
                "pull_request_target",
                "merge_group",
                "push",
                "workflow_dispatch",
                "schedule",
                "",
            },
        )
        self.assertEqual(
            {nome for nome, razao in SEM_INTERVALO.items() if razao is None},
            {"pull_request", "pull_request_target", "merge_group"},
            "os accionamentos que decidem um merge sao os que falham sem intervalo",
        )


class TestLinhaDeComando(ComRepositorio):
    def correr(self, *argumentos: str) -> tuple[int, str]:
        saida, erro = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            codigo = main(["--root", str(self.repo.raiz), "history", *argumentos])
        return codigo, saida.getvalue() + erro.getvalue()

    def test_intervalo_limpo_sai_zero(self) -> None:
        base = self.repo.base
        self.repo.comitar("A", {"services/um.ts": "export const n = 1;\n"})
        codigo, texto = self.correr("--base", base, "--head", "HEAD")
        self.assertEqual(codigo, 0, texto)
        self.assertIn("limpo", texto)

    def test_segredo_no_intervalo_sai_um(self) -> None:
        base = self.repo.base
        self.repo.comitar("A", {FORA_DA_AREA: SEGREDO})
        self.repo.comitar("B", apagar=[FORA_DA_AREA])
        codigo, texto = self.correr("--base", base, "--head", "HEAD")
        self.assertEqual(codigo, 1)
        self.assertNotIn(VALOR, texto)
        self.assertIn("Rode a chave", texto)

    def test_base_irresoluvel_sai_dois(self) -> None:
        codigo, texto = self.correr("--base", "dead" + "beef" * 9, "--head", "HEAD")
        self.assertEqual(codigo, 2)
        self.assertIn("fetch-depth", texto)

    def test_pull_request_sem_base_sai_dois(self) -> None:
        codigo, texto = self.correr("--evento", "pull_request", "--head", "HEAD")
        self.assertEqual(codigo, 2)

    def test_modo_so_arvore_diz_que_a_passagem_nao_correu(self) -> None:
        codigo, texto = self.correr("--evento", "workflow_dispatch", "--head", "HEAD")
        self.assertEqual(codigo, 0)
        self.assertIn("NAO CORRIDA", texto)
        self.assertIn("so-arvore", texto)
        # Uma linha a meio do registo que ninguem le nao e dizer (A9).
        self.assertIn("::warning title=gate 9::", texto)

    def test_intervalo_invertido_num_pull_request_sai_dois(self) -> None:
        """A evasao do YAML trocado: zero commits a dizer-se «limpo» (A3)."""
        base = self.repo.base
        self.repo.comitar("A", {"services/um.ts": "export const n = 1;\n"})
        cabeca = self.repo.git("rev-parse", "HEAD").strip()
        codigo, texto = self.correr(
            "--evento", "pull_request", "--base", cabeca, "--head", base
        )
        self.assertEqual(codigo, 2, texto)
        self.assertIn("zero", texto.lower())
        self.assertNotIn("scan_secrets: limpo", texto)


if __name__ == "__main__":
    unittest.main()
