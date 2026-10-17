"""Exportacao do dicionario: do Markdown ao modelo, e do modelo ao YAML.

O ticket pede: «exportacao do dicionario (cada linha do §3 gera uma entrada)» e
«o CI falha se o ficheiro divergir do Markdown». Os dois estao aqui, contra o
dicionario real e contra textos pequenos escritos para cada regra.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from dict_export.cli import main
from dict_export.exportar import DESTINO, FONTE, construir, exportar, render
from dict_export.markdown import DicionarioIlegivel, ler_linhas, partir_celulas, ultima_versao
from kamba_yaml import load

ROOT = Path(__file__).resolve().parents[3]
TEXTO = (ROOT / FONTE).read_text(encoding="utf-8")


def dicionario(corpo: str, versoes: str = "| 1.0 | Outubro 2026 | Emissao. | Equipa |") -> str:
    return (
        "# Dicionario\n\n## 3. Nomes canonicos por conceito\n\n"
        + corpo
        + "\n## 4. Outra coisa\n\n| Item | Estado |\n|---|---|\n| `nao_conta` | x |\n\n"
        + "## 6. Controlo de versoes\n\n| Versao | Data | Descricao | Autor |\n|---|---|---|---|\n"
        + versoes
        + "\n"
    )


TABELA = (
    "### 3.1 Coisas\n\n"
    "| Conceito | Nome canónico | Substitui | Nota |\n|---|---|---|---|\n"
)


class TestMarkdown(unittest.TestCase):
    def test_cada_linha_do_paragrafo_3_do_dicionario_real_gera_uma_entrada(self) -> None:
        """O criterio do ticket, medido de forma independente do leitor.

        Contam-se as linhas de tabela entre `## 3.` e `## 4.` com uma regex que
        nao partilha codigo com `ler_linhas`: cabecalhos e separadores fora.
        """
        seccao = TEXTO.split("\n## 3. ", 1)[1].split("\n## 4. ", 1)[0]
        linhas = [l for l in seccao.split("\n") if l.startswith("|")]
        de_dados = [
            l for l in linhas
            if not re.match(r"^\|\s*:?-{3,}", l) and not l.startswith("| Conceito |")
        ]
        modelo = construir(TEXTO)
        self.assertEqual(len(modelo.entradas), len(de_dados))
        self.assertGreater(len(de_dados), 50, "o §3 tem dezenas de linhas; isto nao pode ser vacuo")

    def test_so_o_paragrafo_3_conta(self) -> None:
        texto = dicionario(TABELA + "| A | `a` | `a_velho` | — |\n")
        self.assertEqual([l.celulas["conceito"] for l in ler_linhas(texto)], ["A"])

    def test_pipe_dentro_de_crases_nao_parte_a_celula(self) -> None:
        self.assertEqual(partir_celulas("| A | `x | y` | — |"), ["A", "`x | y`", "—"])

    def test_crase_por_fechar_e_erro(self) -> None:
        with self.assertRaises(DicionarioIlegivel):
            partir_celulas("| A | `x | — |")

    def test_cabecalho_desconhecido_e_erro_e_nao_coluna_ignorada(self) -> None:
        texto = dicionario("### 3.1 X\n\n| Conceito | Nome | Sinonimos |\n|---|---|---|\n| A | `a` | `b` |\n")
        with self.assertRaisesRegex(DicionarioIlegivel, "Sinonimos"):
            ler_linhas(texto)

    def test_numero_de_celulas_errado_e_erro(self) -> None:
        texto = dicionario(TABELA + "| A | `a` | — |\n")
        with self.assertRaisesRegex(DicionarioIlegivel, "3 celulas"):
            ler_linhas(texto)

    def test_tabela_indentada_e_erro_e_nao_tabela_ignorada(self) -> None:
        """ANALISE-05 m5: uma tabela com um espaco a frente desaparecia sem aviso."""
        texto = dicionario(TABELA + "| A | `a` | `a_velho` | — |\n\n" + " | B | `b` | `b_velho` | — |\n")
        with self.assertRaisesRegex(DicionarioIlegivel, "indentada"):
            ler_linhas(texto)

    def test_sem_paragrafo_3_e_erro(self) -> None:
        with self.assertRaises(DicionarioIlegivel):
            ler_linhas("# Dicionario\n\n## 2. Convencoes\n")

    def test_ultima_versao_e_a_ultima_linha_do_paragrafo_6(self) -> None:
        texto = dicionario(TABELA + "| A | `a` | `b` | — |\n", "| 1.0 | x | y | z |\n| 1.4 | x | y | z |")
        self.assertEqual(ultima_versao(texto), "1.4")
        self.assertRegex(ultima_versao(TEXTO), r"^\d+\.\d+$")


class TestRegras(unittest.TestCase):
    def modelo(self, linhas: str):
        return construir(dicionario(TABELA + linhas))

    def nomes_das_variantes(self, linhas: str) -> list[str]:
        return [v["nome"] for v in self.modelo(linhas).variantes]

    def test_variante_simples(self) -> None:
        modelo = self.modelo("| Valor | `valor_minor` | `valor_kz` | — |\n")
        self.assertEqual(
            modelo.variantes,
            [{"nome": "valor_kz", "tipo": "nome", "seccao": "3.1", "conceito": "Valor", "canonico": "valor_minor"}],
        )

    def test_palavra_chave_sql_em_maiusculas_nao_e_variante(self) -> None:
        """Emenda 1.5 do dicionario: «`SET` de sessao». Como nome proibido, reprovava
        todo o `SET` de todos os documentos (19 ocorrencias no dia do merge)."""
        self.assertEqual(
            self.nomes_das_variantes("| Contexto | `app.tenant_id` | `SET` de sessão | — |\n| B | `b` | `b_velho` | — |\n"),
            ["b_velho"],
        )

    def test_valor_entre_plicas_e_variante_de_valor(self) -> None:
        modelo = self.modelo("| Preco | `preco_tipo` ∈ {`fixo`} | `preco_kz`, `'exato'` | — |\n")
        self.assertEqual(
            [(v["nome"], v["tipo"]) for v in modelo.variantes], [("preco_kz", "nome"), ("exato", "valor")]
        )

    def test_referencia_a_documento_nao_e_variante(self) -> None:
        self.assertEqual(
            self.nomes_das_variantes(
                "| A | `a` | 3 versoes em `../docs/tecnica/01 §6.2` | — |\n| B | `b` | `b_velho` | — |\n"
            ),
            ["b_velho"],
        )

    def test_expressao_nao_e_variante(self) -> None:
        self.assertEqual(
            self.nomes_das_variantes(
                "| A | `a` | `msisdn_hash+tenant`, `p.stock>0` | — |\n| B | `b` | `b_velho` | — |\n"
            ),
            ["b_velho"],
        )

    def test_nome_canonico_citado_em_prosa_nao_e_variante_nem_contradicao(self) -> None:
        """«`tenants.estado` sem `restrito`» descreve o defeito; nao proibe `restrito`."""
        modelo = self.modelo(
            "| Estado | `ativo`, `restrito` | `tenants.estado` sem `restrito` (`../docs/tecnica/03`) | — |\n"
            "| Coluna | `estado` | `estado_velho` | — |\n"
        )
        self.assertEqual([v["nome"] for v in modelo.variantes], ["estado_velho"])
        self.assertEqual(modelo.contradicoes, [])

    def test_nome_nas_duas_colunas_numa_lista_pura_e_contradicao(self) -> None:
        modelo = self.modelo("| Chaves | `a_minor`, `b_minor` | `a_kz`, `b_minor` | — |\n")
        self.assertEqual([v["nome"] for v in modelo.variantes], ["a_kz"])
        self.assertEqual([c["nome"] for c in modelo.contradicoes], ["b_minor"])

    def test_nome_canonico_noutra_linha_numa_lista_pura_tambem_e_contradicao(self) -> None:
        """ANALISE-05 m5: era descartado em silencio."""
        modelo = self.modelo(
            "| Estado | `estado` | — | — |\n| Velhos | `situacao_nova` | `situacao`, `estado` | — |\n"
        )
        self.assertEqual([v["nome"] for v in modelo.variantes], ["situacao"])
        self.assertEqual([(c["nome"], c["conceito"]) for c in modelo.contradicoes], [("estado", "Velhos")])
        self.assertIn("noutra linha", modelo.contradicoes[0]["razao"])

    def test_a_nota_nunca_salva_uma_variante(self) -> None:
        modelo = self.modelo(
            "| Papeis | `kamba_batch` | `kamba_ops` | O `REVOKE … FROM kamba_app, kamba_ops` falha |\n"
        )
        self.assertEqual([v["nome"] for v in modelo.variantes], ["kamba_ops"])
        self.assertNotIn("kamba_ops", modelo.entradas[0].nomes_nota)
        self.assertIn("kamba_app", modelo.entradas[0].nomes_nota)

    def test_assinatura_de_tabela(self) -> None:
        modelo = self.modelo(
            "| Contacto | `contacts(contact_id, tenant_id, …)` | `x_velho` | — |\n"
            "| Tenant | `platform.tenants(id uuid)` | — | — |\n"
            "| Ledger | **nao** `UNIQUE(provider, referencia)` | — | — |\n"
        )
        self.assertEqual(
            [(t["esquema"], t["nome"], t["colunas"], t["aberta"]) for t in modelo.tabelas],
            [("", "contacts", ["contact_id", "tenant_id"], True), ("platform", "tenants", ["id"], False)],
        )

    def test_dominio_fechado(self) -> None:
        modelo = self.modelo("| Tipo | `tenants.tipo` ∈ {`pme`, `courier`} | `x_velho` | — |\n")
        self.assertEqual(
            modelo.dominios,
            [{"coluna": "tenants.tipo", "valores": ["pme", "courier"], "seccao": "3.1",
              "conceito": "Tipo", "so_no_registo": False}],
        )

    def test_dominio_que_a_celula_declara_como_sendo_so_do_registo(self) -> None:
        """«No registo» antes do nome tira o dominio as colunas (KAM-141, 6 e 9).

        Era uma lista de excepcoes em `ci/canon-lint.yaml` a desfazer, em
        configuracao, o que o §3.2 e o §3.7 ja diziam em prosa. Duas fontes
        para o mesmo facto, e a segunda invisivel a quem le o dicionario.
        """
        modelo = self.modelo(
            "| Vertical | No registo (`registry/*.yaml`): `id` ∈ {`vendedor`, `servicos`} | `x_velho` | — |\n"
        )
        (dominio,) = modelo.dominios
        self.assertEqual(dominio["coluna"], "id")
        self.assertTrue(dominio["so_no_registo"])

    def test_e_a_frase_tem_de_vir_antes_do_nome(self) -> None:
        """Senao bastava a palavra «registo» aparecer na nota para desarmar o dominio."""
        modelo = self.modelo(
            "| Tipo | `tenants.tipo` ∈ {`pme`, `courier`} | `x_velho` | No registo isto nao se aplica |\n"
        )
        (dominio,) = modelo.dominios
        self.assertFalse(dominio["so_no_registo"])

    def test_as_quatro_formas_que_enganavam_a_heuristica(self) -> None:
        """Achado M5 da revisao adversarial, caso a caso.

        A primeira versao procurava «No registo» em **todo** o prefixo da
        celula e localizava a declaracao pelo nome, nao pela posicao. Os
        quatro casos abaixo foram construidos pela revisao, e os quatro
        falhavam em silencio: um dominio marcado a mais faz o gate deixar de
        o verificar **sem dizer nada**. Ficam aqui porque uma correccao a uma
        heuristica so se mantem se os casos que a motivaram estiverem
        escritos.
        """
        casos = (
            ("duas declaracoes, a frase so na primeira",
             "| Vertical | No registo: `id` ∈ {`vendedor`}. E a coluna `tenants.tipo` ∈ {`pme`} "
             "| `x_velho` | — |\n",
             [True, False]),
            ("o mesmo nome duas vezes, a coluna primeiro",
             "| Modulo | Na coluna `modulo` ∈ {`a`, `b`}. No registo: `modulo` ∈ {`c`, `d`} "
             "| `x_velho` | — |\n",
             [False, True]),
            ("«no registo e tambem na coluna» diz o contrario",
             "| Modulo | No registo e tambem na coluna: `modulo` ∈ {`catalogo`, `foto`} "
             "| `x_velho` | — |\n",
             [False]),
            ("«no registo» em prosa inocente antes do nome",
             "| Tipo | O valor fica no registo de auditoria; a coluna `tenants.tipo` ∈ {`pme`} "
             "| `x_velho` | — |\n",
             [False]),
        )
        for nome, linha, esperado in casos:
            with self.subTest(caso=nome):
                modelo = self.modelo(linha)
                self.assertEqual([d["so_no_registo"] for d in modelo.dominios], esperado)

    def test_conceito_repetido_na_mesma_seccao_e_erro(self) -> None:
        with self.assertRaisesRegex(DicionarioIlegivel, "duas"):
            self.modelo("| A | `a` | `a_velho` | — |\n| A | `b` | — | — |\n")

    def test_dicionario_sem_variantes_e_erro_e_nao_gate_vazio(self) -> None:
        with self.assertRaisesRegex(DicionarioIlegivel, "variante nenhuma"):
            self.modelo("| A | `a` | — | — |\n")


class TestDicionarioReal(unittest.TestCase):
    """O que a exportacao tem de dar sobre o dicionario que existe."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.modelo = construir(TEXTO)
        cls.variantes = {v["nome"] for v in cls.modelo.variantes}

    def test_a_versao_do_cabecalho_e_a_da_ultima_emenda(self) -> None:
        """O cabecalho ficou em 1.0 durante treze emendas (KAM-141, linha 7).

        Nao e cosmetica: o dicionario e citado por versao em dezenas de sitios
        («emenda 1.11», «*proposta* (emenda 1.5, KAM-004)»), e um cabecalho que
        diz 1.0 sobre um documento que vai na 1.13 faz quem o le de fora
        acreditar que nenhuma dessas emendas existe. A deriva so se desfaz uma
        vez; o que a impede de voltar e este teste.
        """
        import re

        linhas = TEXTO.splitlines()
        cabecalho = next(l for l in linhas if l.startswith("| Versão |"))
        do_cabecalho = re.search(r"\|\s*Versão\s*\|\s*([0-9]+\.[0-9]+)", cabecalho)
        self.assertIsNotNone(do_cabecalho, f"o cabecalho mudou de forma: {cabecalho!r}")
        emendas = [
            m.group(1)
            for m in (re.match(r"\|\s*([0-9]+\.[0-9]+)\s*\|", l) for l in linhas)
            if m
        ]
        self.assertTrue(emendas, "nao se encontrou nenhuma linha de emenda no §6")
        ultima = max(emendas, key=lambda v: tuple(int(p) for p in v.split(".")))
        self.assertEqual(
            do_cabecalho.group(1), ultima,
            f"o cabecalho diz {do_cabecalho.group(1)} e a ultima emenda do §6 e a {ultima}",
        )

    def test_as_variantes_que_o_criterio_de_aceitacao_nomeia(self) -> None:
        nomeadas = {
            "valor_kz", "callback_hmac_ok", "sig_ok", "consent_log", "consent_ledger",
            "consents", "llm_calls", "msisdn_hash",
        }
        self.assertLessEqual(nomeadas, self.variantes)

    def test_as_duas_que_o_kam_003_deixou_em_divida(self) -> None:
        self.assertIn("kamba_ops", self.variantes)
        self.assertIn("valor_max_pedido_kz", self.variantes)

    def test_o_conjunto_das_variantes_e_exactamente_este(self) -> None:
        """ANALISE-05 m5: citar uma variante entre crases na coluna «Nome» de outra
        linha retirava-a das variantes, e so oito das treze tinham teste.

        O conjunto foi conferido a mao, linha a linha, contra a coluna «Substitui»
        do §3 (dicionario 1.5). Quem emendar o dicionario actualiza esta lista —
        e isso e o que se quer: uma variante nao entra nem sai sem alguem dar por isso.

        Emenda 1.8 (KAM-008): entra `lookup_hmac`, o nome que o bloco do KAM-008
        dava ao HMAC de pesquisa e que o dicionario substitui por
        `contact_endpoints.bsuid_hmac` (linha 3 do KAM-141).

        Emenda 1.12 (KAM-007): entram `preco_modo` e `expires_at`. A emenda 1.11
        tinha resolvido as duas divergencias com o DDL do `docs/tecnica/03` **a
        favor do dicionario** e deixado as formas antigas por registar; a
        revisao adversarial mostrou o que isso custava (achado M3), e este teste
        e o sitio onde se ve que o conjunto cresceu de proposito.
        """
        self.assertEqual(
            sorted((v["nome"], v["tipo"]) for v in self.modelo.variantes),
            sorted(
                [
                    ("msisdn_hash", "nome"), ("consent_log", "nome"), ("consent_ledger", "nome"),
                    ("consents", "nome"), ("valor_max_pedido_kz", "nome"), ("kamba_ops", "nome"),
                    ("preco_kz", "nome"), ("exato", "valor"), ("total_kz", "nome"),
                    ("valor_kz", "nome"), ("callback_hmac_ok", "nome"), ("sig_ok", "nome"),
                    ("llm_calls", "nome"), ("tenant_isolamento", "nome"),
                    ("preco_modo", "nome"), ("expires_at", "nome"),
                    # Emenda 1.13 (KAM-141, linha 4): as tres formas do
                    # `docs/tecnica/04` §6.2, sem as quais o DDL do KAM-053,
                    # copiado do documento como o ticket manda, era recusado
                    # pelo gate sem explicacao.
                    ("hmac_sha256", "nome"), ("status_pull", "nome"),
                    ("humano_auditado", "nome"),
                    ("lookup_hmac", "nome"),
                ]
            ),
        )

    def test_nenhum_nome_canonico_e_variante(self) -> None:
        canonicos = {n for e in self.modelo.entradas for n in e.nomes}
        self.assertEqual(self.variantes & canonicos, set())
        for seguro in ("restrito", "estado", "kamba_batch", "payment.confirmed", "assistant_queries"):
            self.assertNotIn(seguro, self.variantes)

    def test_as_tabelas_do_schema_platform(self) -> None:
        tabelas = {t["nome"]: t for t in reversed(self.modelo.tabelas)}  # a primeira assinatura define
        for nome in ("tenants", "tenant_channels", "entitlements", "contacts", "contact_endpoints"):
            self.assertIn(nome, tabelas)
        self.assertEqual(tabelas["tenants"]["esquema"], "platform")

    def test_o_dicionario_real_nao_tem_contradicoes(self) -> None:
        """A unica que havia era o `manual_max_minor` (KAM-141, linha 1).

        Estava na coluna do nome canonico **e** na coluna «Substitui» da mesma
        linha, e o gate avisava-o em cada execucao. Era lapso de transcricao:
        por simetria com `valor_max_pedido_kz`, a forma antiga seria
        `manual_max_kz`, que documento nenhum escreve. A emenda 1.13 tirou-o da
        coluna errada, e nao se registou uma variante sem sujeito.

        O teste que havia exigia que a contradicao **existisse**, o que fazia
        dele o guarda de um defeito. Este exige que nao haja nenhuma — e o
        mecanismo que a reportava continua provado pelo
        `TestRegras`, com um dicionario construido para o efeito.
        """
        self.assertEqual(self.modelo.contradicoes, [])
        self.assertNotIn("manual_max_minor", self.variantes)
        canonicos = {n for e in self.modelo.entradas for n in e.nomes}
        self.assertIn("manual_max_minor", canonicos)


class TestYaml(unittest.TestCase):
    def test_o_yaml_le_se_de_volta_igual_ao_modelo(self) -> None:
        modelo = construir(TEXTO)
        self.assertEqual(load(render(modelo)), modelo.como_dados())

    def test_texto_com_os_dois_tipos_de_aspas_e_recusado(self) -> None:
        texto = dicionario(TABELA + "| A | `a\"b'c` | `a_velho` | — |\n")
        with self.assertRaisesRegex(DicionarioIlegivel, "aspas"):
            render(construir(texto))

    def test_a_exportacao_e_determinista(self) -> None:
        self.assertEqual(exportar(ROOT), exportar(ROOT))


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        self.raiz = Path(tempfile.mkdtemp(prefix="dict-export-"))
        self.addCleanup(shutil.rmtree, self.raiz, True)
        (self.raiz / "specs").mkdir()
        shutil.copy(ROOT / FONTE, self.raiz / FONTE)

    def test_o_ficheiro_versionado_corresponde_ao_markdown(self) -> None:
        """A invariante do gate, sobre o repositorio real."""
        self.assertEqual(main(["--root", str(ROOT), "--check"]), 0)

    def test_check_sem_ficheiro_falha(self) -> None:
        self.assertEqual(main(["--root", str(self.raiz), "--check"]), 1)

    def test_escrever_e_depois_verificar(self) -> None:
        self.assertEqual(main(["--root", str(self.raiz)]), 0)
        self.assertEqual(main(["--root", str(self.raiz), "--check"]), 0)
        self.assertNotIn(b"\r\n", (self.raiz / DESTINO).read_bytes())

    def test_mudar_o_markdown_sem_regenerar_falha(self) -> None:
        self.assertEqual(main(["--root", str(self.raiz)]), 0)
        caminho = self.raiz / FONTE
        caminho.write_text(
            caminho.read_text(encoding="utf-8").replace("`llm_call_log`", "`llm_registo`"),
            encoding="utf-8",
        )
        self.assertEqual(main(["--root", str(self.raiz), "--check"]), 1)

    def test_editar_o_yaml_a_mao_falha(self) -> None:
        self.assertEqual(main(["--root", str(self.raiz)]), 0)
        destino = self.raiz / DESTINO
        destino.write_text(
            destino.read_text(encoding="utf-8").replace('nome: "valor_kz"', 'nome: "valor_zz"'),
            encoding="utf-8",
        )
        self.assertEqual(main(["--root", str(self.raiz), "--check"]), 1)

    def test_dicionario_ilegivel_e_erro_2_e_nao_ficheiro_em_dia(self) -> None:
        (self.raiz / FONTE).write_text("# sem seccao tres\n", encoding="utf-8")
        self.assertEqual(main(["--root", str(self.raiz), "--check"]), 2)


if __name__ == "__main__":
    unittest.main()
