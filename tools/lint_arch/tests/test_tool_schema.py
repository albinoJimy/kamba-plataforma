"""O *lint* dos esquemas de tool (KAM-028, critero 3): que ele **morde**.

O critero 3 diz «falha o build», e e por isso que este *lint* existe e nao um
teste solto. O que esta bateria prova nao e que o repositorio esta conforme —
isso e uma linha — mas que **um canario falha**: as quatro formas de violar a
regra, uma a uma, cada uma numa arvore temporaria.

A pergunta que o KAM-026 e o KAM-027 ensinaram a fazer: *o que faria este teste
passar com o codigo do lint apagado?* Um `check` que devolvesse sempre `[]`
passaria o primeiro teste desta bateria e falharia os outros cinco. E foi
exactamente por isso que os cinco se escreveram.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lint_arch import tool_schema

ROOT = Path(__file__).resolve().parents[3]

CABECA = "from pydantic import BaseModel, ConfigDict\n\n\n"


class TestRepositorio(unittest.TestCase):
    def test_o_repositorio_esta_conforme(self) -> None:
        self.assertEqual(tool_schema.check(ROOT), [])

    def test_os_quatro_proibidos_sao_os_do_dicionario(self) -> None:
        self.assertEqual(
            tool_schema.PARAMETROS_PROIBIDOS,
            ("tenant_id", "merchant_id", "seller", "account"),
        )

    def test_a_lista_e_a_mesma_que_o_agr_aplica_em_execucao(self) -> None:
        """Duas copias — uma no *lint*, uma na camada — e uma maquina entre elas.

        O *lint* nao pode importar o servico (corre antes de qualquer
        instalacao), pelo que a lista esta escrita duas vezes. Este teste le a
        fonte do AGR e compara: e o que impede as duas de divergirem sem que
        ninguem note.
        """
        import ast

        fonte = (
            ROOT / "services" / "agr" / "src" / "kamba_agr" / "registo" / "validar.py"
        ).read_text(encoding="utf-8")
        arvore = ast.parse(fonte)
        encontrados: tuple[str, ...] | None = None
        for no in ast.walk(arvore):
            if (
                isinstance(no, ast.AnnAssign)
                and isinstance(no.target, ast.Name)
                and no.target.id == "PARAMETROS_PROIBIDOS"
                and isinstance(no.value, ast.Tuple)
            ):
                encontrados = tuple(
                    item.value for item in no.value.elts if isinstance(item, ast.Constant)
                )
        self.assertIsNotNone(encontrados, "o `PARAMETROS_PROIBIDOS` do AGR mudou de forma")
        self.assertEqual(encontrados, tool_schema.PARAMETROS_PROIBIDOS)


class _ComArvore(unittest.TestCase):
    def arvore(
        self, *, dentro_da_tls: bool, fonte: str, nome: str = "ensaio.py"
    ) -> list[str]:
        """Uma arvore com um ficheiro de servico, dentro ou fora de `tls/`.

        `nome` existe para os canarios do `ESCRITAS_DO_PLANO_DE_CONTROLO`, cuja
        chave e `(ficheiro, tabela)`: sem ele nao ha forma de escrever um
        ficheiro **com** o nome dispensado e outro sem.
        """
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            pasta = raiz / "services" / "agr" / "src" / "kamba_agr"
            if dentro_da_tls:
                pasta = pasta / "tls"
            pasta.mkdir(parents=True)
            (pasta / nome).write_text(fonte, encoding="utf-8")
            return tool_schema.check(raiz)


class TestCanarios(_ComArvore):
    def test_um_parametro_proibido_falha(self) -> None:
        for proibido in tool_schema.PARAMETROS_PROIBIDOS:
            with self.subTest(parametro=proibido):
                achados = self.arvore(
                    dentro_da_tls=True,
                    fonte=CABECA
                    + "class Args(BaseModel):\n"
                    '    model_config = ConfigDict(extra="forbid")\n'
                    f"    {proibido}: str\n",
                )
                self.assertEqual(len(achados), 1, achados)
                self.assertIn(proibido, achados[0])
                self.assertIn("ToolContext", achados[0])

    def test_sem_extra_forbid_falha(self) -> None:
        achados = self.arvore(
            dentro_da_tls=True,
            fonte=CABECA + "class Args(BaseModel):\n    sku: str\n",
        )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("forbid", achados[0])

    def test_extra_allow_tambem_falha(self) -> None:
        """`extra="allow"` nao e «nao declarou»: e declarou o contrario."""
        achados = self.arvore(
            dentro_da_tls=True,
            fonte=CABECA
            + "class Args(BaseModel):\n"
            '    model_config = ConfigDict(extra="allow")\n'
            "    sku: str\n",
        )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("forbid", achados[0])

    def test_escrita_no_platform_fora_da_tls_falha(self) -> None:
        for instrucao in (
            "INSERT INTO platform.tool_audit (tool) VALUES (%s)",
            "UPDATE platform.conversations SET mode = %s",
            "DELETE FROM platform.handoffs WHERE handoff_id = %s",
        ):
            with self.subTest(instrucao=instrucao.split()[0]):
                achados = self.arvore(
                    dentro_da_tls=False, fonte=f'SQL = "{instrucao}"\n'
                )
                self.assertEqual(len(achados), 1, achados)
                self.assertIn("unica via de escrita", achados[0])

    def test_uma_subclasse_indirecta_tambem_falha(self) -> None:
        """A primeira versao reconhecia so heranca **directa** de `BaseModel`.

        Com isso, duas linhas escapavam as duas verificacoes e o *lint*
        devolvia `conforme` sobre um esquema com `tenant_id`. Medido pela
        revisao adversarial numa arvore de ensaio.
        """
        achados = self.arvore(
            dentro_da_tls=True,
            fonte=CABECA
            + "class Base(BaseModel):\n"
            '    model_config = ConfigDict(extra="forbid")\n\n\n'
            "class Args(Base):\n"
            "    tenant_id: str\n"
            "    seller: str\n",
        )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("tenant_id", achados[0])
        self.assertIn("seller", achados[0])

    def test_o_extra_forbid_herda_se(self) -> None:
        """O Pydantic herda a configuracao; exigi-la outra vez recusava codigo certo."""
        achados = self.arvore(
            dentro_da_tls=True,
            fonte=CABECA
            + "class Base(BaseModel):\n"
            '    model_config = ConfigDict(extra="forbid")\n\n\n'
            "class Args(Base):\n"
            "    sku: str\n",
        )
        self.assertEqual(achados, [])

    def test_uma_base_de_fora_do_ficheiro_e_achado_e_nao_silencio(self) -> None:
        """Falha fechada: o *lint* nao importa nada para a descobrir."""
        achados = self.arvore(
            dentro_da_tls=True,
            fonte="from .comum import Base\n\n\nclass Args(Base):\n    sku: str\n",
        )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("nao define", achados[0])

    def test_uma_excepcao_nao_e_um_esquema(self) -> None:
        achados = self.arvore(
            dentro_da_tls=True,
            fonte="class ErroDeTool(Exception):\n    pass\n",
        )
        self.assertEqual(achados, [])

    def test_uma_escrita_em_varias_linhas_tambem_falha(self) -> None:
        """O SQL desta casa esta em literais de varias linhas.

        A primeira versao varria **linha a linha** com um padrao que atravessa
        espaco em branco: um `INSERT INTO` com a tabela na linha seguinte era
        invisivel. Apanhado pela revisao adversarial.
        """
        achados = self.arvore(
            dentro_da_tls=False,
            fonte='SQL = """\nINSERT INTO\n  platform.tool_audit (tool)\nVALUES (%s)\n"""\n',
        )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("unica via de escrita", achados[0])

    def test_a_mesma_escrita_dentro_da_tls_passa(self) -> None:
        achados = self.arvore(
            dentro_da_tls=True,
            fonte='SQL = "INSERT INTO platform.tool_audit (tool) VALUES (%s)"\n',
        )
        self.assertEqual(achados, [])

    def test_uma_leitura_fora_da_tls_passa(self) -> None:
        """O `conversa.py` do KAM-025 le a `conversations`, e isso e a admissao."""
        achados = self.arvore(
            dentro_da_tls=False,
            fonte='SQL = "SELECT mode FROM platform.conversations WHERE id = %s"\n',
        )
        self.assertEqual(achados, [])

    def test_a_escrita_do_plano_de_controlo_declarada_passa(self) -> None:
        """O CAS do KAM-034 em `consultas.py`, declarado por `(ficheiro, tabela)`."""
        achados = self.arvore(
            dentro_da_tls=False,
            nome="consultas.py",
            fonte='SQL = "UPDATE platform.handoffs SET status = %s"\n',
        )
        self.assertEqual(achados, [])

    def test_outra_tabela_no_mesmo_ficheiro_dispensado_continua_a_falhar(self) -> None:
        """**E a propriedade que faz a chave ser `(ficheiro, tabela)`.**

        Um `consultas.py` dispensado em bloco deixava passar um `UPDATE
        platform.orders` na linha seguinte — e e exactamente isso que esta regra
        existe para apanhar. Com a chave por par, o ficheiro dispensado para uma
        tabela continua a morder em todas as outras.
        """
        for tabela in ("orders", "contacts", "conversations", "tenants"):
            with self.subTest(tabela=tabela):
                achados = self.arvore(
                    dentro_da_tls=False,
                    nome="consultas.py",
                    fonte=f'SQL = "UPDATE platform.{tabela} SET x = %s"\n',
                )
                self.assertEqual(len(achados), 1, achados)
                self.assertIn("unica via de escrita", achados[0])

    def test_a_mesma_tabela_noutro_ficheiro_continua_a_falhar(self) -> None:
        """A dispensa e do par, logo nao viaja com a tabela."""
        achados = self.arvore(
            dentro_da_tls=False,
            nome="turno.py",
            fonte='SQL = "UPDATE platform.handoffs SET status = %s"\n',
        )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("unica via de escrita", achados[0])

    def test_um_insert_ou_delete_na_tabela_dispensada_continua_a_falhar(self) -> None:
        """**A dispensa e por verbo, e a primeira versao deixou-o de fora.**

        Ela argumentava que distinguir verbos era redundante porque «o `GRANT`
        por coluna da revisao `0011` da-a melhor: o `kamba_app` nao tem `DELETE`
        em `platform.handoffs`». Metade era falso — a `0011` concede
        `GRANT SELECT, INSERT`, pelo que um `INSERT` escrito ali **passava o
        *lint* e corria na base**. E o canon atribui a criacao da passagem ao HND
        e a purga ao `kamba_batch`. Achado 5 da revisao adversarial.
        """
        for instrucao in (
            "INSERT INTO platform.handoffs (handoff_id) VALUES (%s)",
            "DELETE FROM platform.handoffs WHERE handoff_id = %s",
        ):
            with self.subTest(verbo=instrucao.split()[0]):
                achados = self.arvore(
                    dentro_da_tls=False,
                    nome="consultas.py",
                    fonte=f'SQL = "{instrucao}"\n',
                )
                self.assertEqual(len(achados), 1, achados)
                self.assertIn("unica via de escrita", achados[0])

    def test_um_identificador_entre_aspas_tambem_falha(self) -> None:
        """**A regressao que a captura da tabela introduziu.**

        O padrao era `platform\\.` e apanhava `UPDATE platform."orders"`; passar
        a `platform\\.(\\w+)` para saber a tabela fez o `\\w+` nao casar a aspa,
        e com isso uma escrita com identificador citado deixou de morder — num
        *gate* de bloqueio, e para **todas** as tabelas. Achado 4 da revisao
        adversarial.
        """
        for instrucao in (
            'UPDATE platform."orders" SET x = %s',
            'INSERT INTO platform."handoffs" (handoff_id) VALUES (%s)',
            'DELETE FROM platform."conversations" WHERE id = %s',
        ):
            with self.subTest(instrucao=instrucao.split()[0]):
                achados = self.arvore(
                    dentro_da_tls=False, fonte=f"SQL = '{instrucao}'\n"
                )
                self.assertEqual(len(achados), 1, achados)
                self.assertIn("unica via de escrita", achados[0])

    def test_a_tabela_dispensada_entre_aspas_nao_escapa_a_regra_do_verbo(self) -> None:
        """As aspas nao sao uma terceira via: o `update` citado passa (e a mesma
        escrita) e o `insert` citado falha (e a mesma fronteira)."""
        passa = self.arvore(
            dentro_da_tls=False,
            nome="consultas.py",
            fonte="SQL = 'UPDATE platform.\"handoffs\" SET status = %s'\n",
        )
        self.assertEqual(passa, [])
        falha = self.arvore(
            dentro_da_tls=False,
            nome="consultas.py",
            fonte="SQL = 'INSERT INTO platform.\"handoffs\" (handoff_id) VALUES (%s)'\n",
        )
        self.assertEqual(len(falha), 1, falha)


class TestOQueNaoEAchado(_ComArvore):
    def test_um_modelo_conforme_passa(self) -> None:
        achados = self.arvore(
            dentro_da_tls=True,
            fonte=CABECA
            + "class Args(BaseModel):\n"
            '    model_config = ConfigDict(extra="forbid")\n'
            "    sku: str\n",
        )
        self.assertEqual(achados, [])

    def test_o_dict_literal_conta_como_extra_forbid(self) -> None:
        achados = self.arvore(
            dentro_da_tls=True,
            fonte=CABECA
            + "class Args(BaseModel):\n"
            '    model_config = {"extra": "forbid"}\n'
            "    sku: str\n",
        )
        self.assertEqual(achados, [])

    def test_uma_classe_que_nao_e_base_model_nao_e_esquema(self) -> None:
        achados = self.arvore(
            dentro_da_tls=True,
            fonte="class Pedido:\n    tenant_id: str\n",
        )
        self.assertEqual(achados, [])

    def test_um_modelo_fora_da_tls_nao_e_esquema_de_tool(self) -> None:
        """O `registo/esquema.py` le `registry/*.yaml` e nao vai ao modelo."""
        achados = self.arvore(
            dentro_da_tls=False,
            fonte=CABECA + "class Vertical(BaseModel):\n    tenant_id: str\n",
        )
        self.assertEqual(achados, [])

    def test_um_ficheiro_que_nao_compila_e_achado_e_nao_silencio(self) -> None:
        achados = self.arvore(dentro_da_tls=True, fonte="class Args(BaseModel\n")
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("nao compila", achados[0])


if __name__ == "__main__":
    unittest.main()
