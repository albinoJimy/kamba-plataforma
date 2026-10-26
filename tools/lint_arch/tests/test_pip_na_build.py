"""`RUN pip install <bloqueado>` num Dockerfile reprova o lint (KAM-030).

E a quarta clausula do criterio 1 do KAM-030 — «`pip install litellm` na *build*
reprova o lint» — e era a **unica das quatro sem maquina a impo-la**: a entrada
`litellm` de `tools/blocklist.yaml` e `kind: any` e esta la desde o KAM-067, mas
o leitor de Dockerfiles so lia `FROM` e `ARG`, pelo que nenhuma declaracao PyPI
saia de um Dockerfile para a lista se aplicar.

**Os canarios estao nas duas direccoes**, e sao o que torna isto uma prova:
`test_sem_pip_install_nao_ha_achado` garante que nao se inventam achados, e
`test_um_pacote_permitido_nao_da_achado` garante que a leitura nao esta a
transformar qualquer token em pacote — que foi o defeito da primeira versao, em
que `RUN pip install -r req.txt && pip3 install x` dava os nomes `&&`, `pip3` e
`install` como pacotes.
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

from lint_arch import manifests
from lint_arch.cli import check_dependencies

#: Uma imagem base por digest, para que o Dockerfile de ensaio nao produza
#: achados que nao sejam o que se esta a medir.
BASE = (
    "FROM python:3.12-slim-trixie@sha256:"
    "a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1\n"
)


def _blocklist() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2] / "blocklist.yaml"


class _ComDockerfile(unittest.TestCase):
    def _arvore(self, corpo: str) -> pathlib.Path:
        raiz = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        pasta = raiz / "services" / "ensaio"
        pasta.mkdir(parents=True)
        (pasta / "Dockerfile").write_bytes((BASE + corpo).encode("utf-8"))
        return raiz

    def _pacotes(self, corpo: str) -> list[str]:
        raiz = self._arvore(corpo)
        return [
            d.name
            for d in manifests.from_dockerfile(
                raiz / "services" / "ensaio" / "Dockerfile", raiz
            )
            if d.ecosystem == manifests.PYPI
        ]

    def _achados(self, corpo: str) -> list[str]:
        return check_dependencies(self._arvore(corpo), _blocklist())


class TestOsBloqueadosSaoApanhados(_ComDockerfile):
    def test_o_litellm_reprova(self) -> None:
        achados = self._achados("RUN pip install litellm==1.82.7\n")
        self.assertEqual(len(achados), 1)
        self.assertIn("litellm", achados[0])

    def test_o_litellm_sem_versao_reprova(self) -> None:
        """Sem versao nao se prova que esta acima de 1.83.0."""
        self.assertTrue(self._achados("RUN pip install litellm\n"))

    def test_o_langgraph_api_reprova(self) -> None:
        """Nao e so o LiteLLM: o ADR-002 corria o mesmo risco."""
        achados = self._achados("RUN pip install langgraph-api\n")
        self.assertEqual(len(achados), 1)
        self.assertIn("langgraph-api", achados[0])

    def test_com_continuacao_de_linha(self) -> None:
        self.assertTrue(
            self._achados("RUN pip install --no-cache-dir \\\n    litellm==1.82.8\n")
        )

    def test_o_segundo_pip_install_da_mesma_linha(self) -> None:
        """A primeira versao perdia-o: levava o resto da linha como pacotes."""
        achados = self._achados(
            "RUN pip install -r requirements.txt && pip3 install langgraph-api\n"
        )
        self.assertEqual(len(achados), 1)
        self.assertIn("langgraph-api", achados[0])

    def test_as_quatro_formas_de_invocar_o_pip(self) -> None:
        for comando in (
            "pip install litellm",
            "pip3 install litellm",
            "python -m pip install litellm",
            "uv pip install litellm",
        ):
            with self.subTest(comando=comando):
                self.assertTrue(self._achados(f"RUN {comando}\n"), comando)

    def test_com_variavel_de_ambiente_a_frente(self) -> None:
        self.assertTrue(self._achados("RUN PIP_NO_CACHE_DIR=1 pip install litellm\n"))

    def test_as_quatro_formas_que_a_revisao_adversarial_encontrou(self) -> None:
        """O achado 8: quatro formas que a primeira versao deixava passar.

        `sh -c "…"` e `bash -lc '…'` sao a forma mais comum de envolver um
        comando; a forma **exec** (`RUN [...]`) e JSON e nao passa por shell
        nenhum; o tab depois do `RUN` o Docker aceita; e uma opcao **antes** do
        `install` tambem.
        """
        for corpo in (
            'RUN sh -c "pip install litellm"\n',
            "RUN bash -lc 'pip install litellm'\n",
            'RUN ["pip", "install", "litellm"]\n',
            "RUN\tpip install litellm\n",
            "RUN pip --no-cache-dir install litellm\n",
        ):
            with self.subTest(corpo=corpo.strip()):
                self.assertTrue(self._achados(corpo), corpo)

    def test_o_que_continua_a_passar_esta_declarado(self) -> None:
        """**Tres formas continuam a escapar, e estao na divida 119.**

        Fecha-las exigia um analisador de shell a serio, e nenhuma e a forma em
        que alguem escreve um `pip install` por distraccao. Este teste existe
        para a lacuna ser **medida** e nao suposta: no dia em que alguem a
        fechar, ele falha e manda apagar a linha da divida.
        """
        for corpo in (
            'RUN eval "pip install litellm"\n',
            "RUN echo litellm | xargs pip install\n",
        ):
            with self.subTest(corpo=corpo.strip()):
                self.assertEqual(
                    self._achados(corpo), [],
                    "se isto passou a ser apanhado, apague a linha 119 das "
                    "dividas e este caso",
                )

    def test_a_versao_vai_na_declaracao(self) -> None:
        """O achado 21: a `spec` saia vazia e a mensagem mentia.

        Com a `spec` vazia, uma entrada com `forbidden_below` dava achado mesmo
        correctamente fixada, a dizer «a versao nao esta fixada exactamente
        ('')». Para o `litellm` o desfecho era o desejado — o critero 1 quer que
        **qualquer** `pip install litellm` reprove —, mas a proxima entrada PyPI
        com piso ganhava um falso positivo.
        """
        raiz = self._arvore("RUN pip install litellm==1.104.2\n")
        decls = [
            d
            for d in manifests.from_dockerfile(
                raiz / "services" / "ensaio" / "Dockerfile", raiz
            )
            if d.ecosystem == manifests.PYPI
        ]
        self.assertEqual([(d.name, d.spec) for d in decls], [("litellm", "==1.104.2")])


class TestNaoSeInventamPacotes(_ComDockerfile):
    """Os canarios pelo outro lado."""

    def test_sem_pip_install_nao_ha_achado(self) -> None:
        self.assertEqual(self._achados("RUN echo ola\n"), [])
        self.assertEqual(self._pacotes("RUN echo ola\n"), [])

    def test_um_pacote_permitido_nao_da_achado(self) -> None:
        self.assertEqual(self._achados("RUN pip install httpx==0.28.1\n"), [])

    def test_as_opcoes_nao_sao_pacotes(self) -> None:
        pacotes = self._pacotes(
            "RUN pip install --no-cache-dir -i https://pypi.org/simple "
            "--target /app httpx==0.28.1\n"
        )
        self.assertEqual(pacotes, ["httpx"])

    def test_o_requirements_nao_conta_como_pacote(self) -> None:
        """Aquele ficheiro e varrido por si; contar o nome dele era um achado duplo."""
        self.assertEqual(self._pacotes("RUN pip install -r requirements.txt\n"), [])

    def test_os_operadores_de_shell_nao_sao_pacotes(self) -> None:
        pacotes = self._pacotes(
            "RUN pip install httpx && echo feito; pip install --upgrade pip\n"
        )
        self.assertNotIn("&&", pacotes)
        self.assertNotIn("echo", pacotes)
        self.assertNotIn("install", pacotes)
        self.assertNotIn("feito", pacotes)

    def test_um_caminho_ou_url_nao_e_nome(self) -> None:
        for alvo in (".", "/tmp/roda.whl", "git+https://exemplo.ao/x.git"):
            with self.subTest(alvo=alvo):
                self.assertEqual(self._pacotes(f"RUN pip install {alvo}\n"), [])

    def test_uma_linha_que_nao_e_RUN_nao_se_le(self) -> None:
        """`CMD` ou `ENTRYPOINT` com `pip install` nao e a *build*.

        Corre em execucao, nao ao construir a imagem, e o critero fala da
        *build*. Um `CMD` destes e defeito de outra natureza — e seria apanhado
        pelo arranque, nao por um lint de manifestos.
        """
        self.assertEqual(self._pacotes('CMD ["pip", "install", "litellm"]\n'), [])
        self.assertEqual(self._pacotes("CMD pip install litellm\n"), [])


class TestOsNomesSaoNormalizados(_ComDockerfile):
    def test_o_sublinhado_e_o_hifen_batem_na_mesma_entrada(self) -> None:
        """PEP 503: `langgraph_api` e `langgraph-api` sao o mesmo pacote."""
        self.assertTrue(self._achados("RUN pip install langgraph_api\n"))

    def test_o_extra_nao_entra_no_nome(self) -> None:
        pacotes = self._pacotes("RUN pip install litellm[proxy]==1.82.7\n")
        self.assertEqual(pacotes, ["litellm"])


if __name__ == "__main__":
    unittest.main()
