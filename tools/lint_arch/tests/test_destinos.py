"""O inventario de clientes de saida, e o canario dele (KAM-069, criterio 4).

**O canario e metade do valor deste ficheiro.** O repositorio esta conforme — o
`test_o_repositorio_esta_conforme` afirma-o —, e «0 achados» sobre uma arvore
conforme e uma linha que um `check` vazio tambem imprime. As duas direccoes da
verificacao provam-se contra arvores construidas para as quebrar:

* um ficheiro com o FQDN de um subprocessador **fora** do inventario;
* uma entrada que diz consultar o *gate* e cujo ficheiro perdeu a chamada;
* uma entrada cujo ficheiro ja nao existe;
* uma entrada sem *gate* e sem credor.

As arvores sao temporarias e nao *fixtures* no disco, e a razao e medida: um
ficheiro de *fixture* com `graph.facebook.com` dentro entrava na varredura de
numeros do *gate* 7 e nas superficies do `canon_lint`, e um canario que custa
entradas noutros inventarios e um canario que alguem acaba por apagar.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lint_arch import destinos, structure

RAIZ = Path(__file__).resolve().parents[3]


#: O minimo que satisfaz a metade da **declaracao** numa arvore temporaria.
#:
#: Sem isto, cada canario levava os sete achados de «entrada morta» em cima do
#: que queria medir, e a asercao sobre o achado da **descoberta** media as duas
#: metades juntas. Com os ficheiros do inventario presentes, cada canario mede
#: o que o seu nome diz.
GATE_MINIMO = (
    "from . import destinos as destinos_mod\n"
    "self._destinos.autorizar(tenant, fornecedor, finalidade)\n"
)


def _arvore(
    ficheiros: dict[str, str], com_inventario: bool = True
) -> tempfile.TemporaryDirectory:
    temporaria = tempfile.TemporaryDirectory()
    raiz = Path(temporaria.name)
    conteudos: dict[str, str] = {}
    if com_inventario:
        for relativo, cliente in destinos.CLIENTES_DE_SAIDA.items():
            conteudos[relativo] = GATE_MINIMO if cliente.consulta_o_gate else "vazio\n"
    conteudos.update(ficheiros)
    for relativo, conteudo in conteudos.items():
        caminho = raiz / relativo
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(conteudo, encoding="utf-8")
    return temporaria


class TestRepositorio(unittest.TestCase):
    def test_o_repositorio_esta_conforme(self) -> None:
        self.assertEqual(destinos.check(RAIZ), [])

    def test_o_check_entra_no_structure_e_nao_num_comando_novo(self) -> None:
        """Um comando novo nao custa nada; um *job* novo custava.

        Um *job* no `.github/workflows/ci.yaml` acrescenta um contexto exigido ao
        *ruleset* de `main`, e isso e alteracao de regra de bloqueio — decisao do
        fundador. O `structure.check` ja corre no *gate* 2, que e onde uma
        verificacao estatica da fonte pertence.
        """
        fonte = (RAIZ / "tools" / "lint_arch" / "structure.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("destinos.check(root", fonte)
        self.assertEqual(structure.check(RAIZ), [])

    def test_o_cliente_de_llm_e_o_unico_que_consulta_o_gate(self) -> None:
        """A medicao que a caixa do criterio 4 leva.

        Sete pontos de invocacao no criterio, **um** a consultar o *gate*. O
        numero esta aqui e nao numa frase de um bloco, porque aqui um `grep`
        encontra-o e um vermelho avisa quando ele mudar.
        """
        consultam = [
            caminho
            for caminho, cliente in destinos.CLIENTES_DE_SAIDA.items()
            if cliente.consulta_o_gate
        ]
        self.assertEqual(consultam, ["services/agr/src/kamba_agr/llm/cliente.py"])

    def test_cada_entrada_sem_gate_tem_credor(self) -> None:
        for caminho, cliente in destinos.CLIENTES_DE_SAIDA.items():
            with self.subTest(caminho=caminho):
                if not cliente.consulta_o_gate:
                    self.assertTrue(cliente.credor)
                self.assertTrue(cliente.razao.strip())

    def test_cada_finalidade_declarada_esta_no_dominio_da_coluna(self) -> None:
        from subprocessadores.inventario import FINALIDADES

        for caminho, cliente in destinos.CLIENTES_DE_SAIDA.items():
            with self.subTest(caminho=caminho):
                self.assertIn(cliente.finalidade, FINALIDADES)
        for finalidade in destinos.FINALIDADES_SEM_CLIENTE:
            with self.subTest(finalidade=finalidade):
                self.assertIn(finalidade, FINALIDADES)

    def test_as_finalidades_sem_cliente_nao_tem_mesmo_cliente(self) -> None:
        """Nos dois sentidos: a lista das que faltam nao pode mentir.

        Uma finalidade declarada «sem cliente» que passasse a ter um era uma
        conta desactualizada a dizer que o *gate* cobre menos do que cobre — e e
        exactamente a direccao em que esta casa nao aceita numeros velhos.
        """
        declaradas = {c.finalidade for c in destinos.CLIENTES_DE_SAIDA.values()}
        self.assertEqual(declaradas & set(destinos.FINALIDADES_SEM_CLIENTE), set())


class TestCanario(unittest.TestCase):
    """Cada direccao da verificacao, contra uma arvore feita para a quebrar."""

    def test_um_cliente_novo_com_fqdn_e_apanhado(self) -> None:
        with _arvore(
            {
                "packages/core-ts/src/novo/cliente.ts": (
                    'export const BASE = "https://api.openai.com/v1";\n'
                )
            }
        ) as nome:
            achados = destinos.check(
                Path(nome), caminhos=["packages/core-ts/src/novo/cliente.ts"]
            )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("fora do inventario", achados[0])
        self.assertIn("api.openai.com", achados[0])

    def test_um_import_de_sdk_de_fornecedor_e_apanhado(self) -> None:
        for relativo, fonte in (
            ("services/agr/src/kamba_agr/novo.py", "import anthropic\n"),
            ("packages/core-ts/src/novo.ts", 'import x from "@aws-sdk/client-s3";\n'),
            ("libs/py-core/src/kamba_core/novo.py", "from openai import OpenAI\n"),
        ):
            with self.subTest(relativo=relativo):
                with _arvore({relativo: fonte}) as nome:
                    achados = destinos.check(Path(nome), caminhos=[relativo])
                self.assertEqual(len(achados), 1, achados)
                self.assertIn("SDK de fornecedor", achados[0])

    def test_um_nome_parecido_nao_e_um_import_de_sdk(self) -> None:
        """O canario do canario: um `substring` apanhava cinco ficheiros do AGR.

        `litellm_virtual_key` e o nome de um segredo (`ops/secrets-inventory.yaml`)
        e `KAMBA_LLM_PROXY_URL` e o endereco do proxy interno. Nenhum dos dois e
        um SDK, e um *lint* que os apanhasse era um *lint* que alguem desligava.
        """
        with _arvore(
            {
                "services/agr/src/kamba_agr/nada.py": (
                    "REF = 'litellm_virtual_key/x'\n"
                    "URL = os.environ['KAMBA_LLM_PROXY_URL']\n"
                    "# o proxy litellm corre na rede interna\n"
                )
            }
        ) as nome:
            achados = destinos.check(
                Path(nome), caminhos=["services/agr/src/kamba_agr/nada.py"]
            )
        self.assertEqual(achados, [])

    def test_um_ficheiro_fora_do_ambito_nao_e_apanhado(self) -> None:
        """Documentos, `egress.yaml` e testes citam FQDN e nao sao clientes."""
        for relativo in (
            "docs/tecnica/08_Seguranca_Conformidade.md",
            "services/gwy/egress.yaml",
            "packages/core-ts/tests/outbound.limites.test.ts",
            "infra/egress/litellm.yaml",
        ):
            with self.subTest(relativo=relativo):
                with _arvore({relativo: "api.openai.com\n"}) as nome:
                    self.assertEqual(
                        destinos.check(Path(nome), caminhos=[relativo]), []
                    )

    def test_a_chamada_do_gate_retirada_e_apanhada(self) -> None:
        """A direccao que tem valor hoje, e e a que um *import* nao prova.

        Um ficheiro que importe o modulo e nunca chame `.autorizar(` deixa o
        caminho de saida sem barreira, e nada no *import* o denuncia.
        """
        relativo = "services/agr/src/kamba_agr/llm/cliente.py"
        for fonte, falta in (
            ("from . import destinos as destinos_mod\n", "a chamada"),
            ("self._destinos.autorizar(t, f, p)\n", "o `import`"),
            ("# nada aqui\n", "a chamada"),
        ):
            with self.subTest(fonte=fonte.strip()):
                with _arvore({relativo: fonte}) as nome:
                    achados = destinos.check(Path(nome), caminhos=[relativo])
                self.assertTrue(achados, "o canario nao mordeu")
                self.assertIn("declara que consulta o *gate*", achados[0])
                self.assertIn(falta, achados[0])

    def test_a_chamada_e_o_import_juntos_passam(self) -> None:
        """O canario positivo: um predicado que recusasse tudo passava os tres
        casos acima."""
        relativo = "services/agr/src/kamba_agr/llm/cliente.py"
        with _arvore(
            {
                relativo: (
                    "from . import destinos as destinos_mod\n"
                    "self._destinos.autorizar(t, f, p)\n"
                )
            }
        ) as nome:
            self.assertEqual(destinos.check(Path(nome), caminhos=[relativo]), [])

    def test_uma_entrada_morta_e_apanhada(self) -> None:
        """Um inventario com entradas mortas descreve uma arvore que nao existe.

        E o caso que acontece a seguir a um ficheiro mudar de nome: o caminho de
        saida continua la, com outro nome, e **fora** do inventario — pelo que a
        descoberta tambem o apanharia se ele tivesse FQDN, e nao o apanharia se
        nao tivesse. E esta a entrada que avisa.
        """
        with _arvore({"README.md": "vazio\n"}, com_inventario=False) as nome:
            achados = destinos.check(Path(nome), caminhos=["README.md"])
        self.assertEqual(len(achados), len(destinos.CLIENTES_DE_SAIDA), achados)
        for achado in achados:
            self.assertIn("entrada morta", achado)


if __name__ == "__main__":
    unittest.main()
