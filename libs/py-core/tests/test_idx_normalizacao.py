"""A normalizacao PT-AO sem base de dados (KAM-062, `docs/tecnica/05` §5).

O lexico destes ensaios e o **ilustrativo** do §5.1 — NAO VERIFICADO, e so
*fixture*: nenhum deles e lexico de producao. O comportamento contra o
PostgreSQL (RLS cruzada, vocabulario por `ts_stat`, reindexacao, a semelhanca
do `pg_trgm` cruzada com a de `semelhanca`) mede-se no *gate* 8, em
`db/tests_produtos/test_normalizacao.py`.
"""

from __future__ import annotations

import ast
import statistics
import time
import unittest
from pathlib import Path

from kamba_core.idx import normalizacao as n
from kamba_core.idx import numeros

A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"

#: O lexico ilustrativo do §5.1 (NAO VERIFICADO), mais as unidades do passo 4
#: e as *stopwords* do passo 7, como linhas do `idx.termo_canonico`.
LEXICO_ILUSTRATIVO = (
    {"tenant_id": None, "tipo": "sinonimo", "termo": "geleira", "canonico": "frigorifico", "peso": 0.8},
    {"tenant_id": None, "tipo": "sinonimo", "termo": "celular", "canonico": "telemovel"},
    {"tenant_id": None, "tipo": "sinonimo", "termo": "telefone", "canonico": "telemovel|telefone fixo"},
    {"tenant_id": None, "tipo": "marca", "termo": "ifone", "canonico": "iphone"},
    {"tenant_id": None, "tipo": "marca", "termo": "aifone", "canonico": "iphone"},
    {"tenant_id": None, "tipo": "marca", "termo": "i phone", "canonico": "iphone"},
    {"tenant_id": None, "tipo": "erro_comum", "termo": "niker", "canonico": "nike"},
    {"tenant_id": None, "tipo": "erro_comum", "termo": "naike", "canonico": "nike"},
    {"tenant_id": None, "tipo": "unidade", "termo": "litros", "canonico": "l"},
    {"tenant_id": None, "tipo": "unidade", "termo": "lt", "canonico": "l"},
    {"tenant_id": None, "tipo": "unidade", "termo": "giga", "canonico": "gb"},
    {"tenant_id": None, "tipo": "unidade", "termo": "polegadas", "canonico": "pol"},
    {"tenant_id": None, "tipo": "unidade", "termo": '"', "canonico": "pol"},
    *(
        {"tenant_id": None, "tipo": "stopword", "termo": p, "canonico": "-"}
        for p in ("quero", "queria", "tem", "vende", "ai", "por favor", "mano", "meu")
    ),
)

VOCABULARIO = n.Vocabulario.de_frequencias(
    {"nike": 5, "air": 2, "frigorifico": 3, "lg": 1, "telemovel": 4, "samsung": 2, "iphone": 1}
)


def lexico(tenant: str | None = None, linhas=LEXICO_ILUSTRATIVO, versao: int = 7) -> n.Lexico:
    return n.Lexico.de_linhas(linhas, tenant, norm_versao=versao)


def norm(texto: str, origem: str = "texto", tenant: str | None = None, **kw) -> n.Normalizacao:
    return n.normalizar(
        texto, tenant, origem, lexico=lexico(tenant), vocabulario=kw.get("vocabulario", VOCABULARIO)
    )


class TestContrato(unittest.TestCase):
    """Criterio 1: nove passos, os cinco campos, e pura."""

    def test_devolve_os_cinco_campos(self) -> None:
        saida = norm("quero uma geleira LG até 250 mil").como_dict()
        for campo in ("q_norm", "q_or", "restricoes", "tokens_nao_resolvidos", "norm_versao"):
            self.assertIn(campo, saida)
        self.assertEqual(saida["norm_versao"], 7)

    def test_mesma_entrada_mesma_saida_em_100_execucoes(self) -> None:
        frases = ("quero uma geleira LG até 250 mil", "niker air 42", "xyzq", "telefone")
        for frase in frases:
            with self.subTest(frase=frase):
                primeira = norm(frase)
                for _ in range(100):
                    self.assertEqual(norm(frase), primeira)

    def test_o_modulo_nao_importa_rede_nem_llm(self) -> None:
        """Sem rede: os `import` dos dois modulos sao todos da biblioteca de base."""
        permitidos = {"__future__", "re", "unicodedata", "collections.abc", "dataclasses", "typing"}
        raiz = Path(n.__file__).parent
        for nome in ("normalizacao.py", "numeros.py"):
            arvore = ast.parse((raiz / nome).read_text(encoding="utf-8"))
            importados = set()
            for no in ast.walk(arvore):
                if isinstance(no, ast.Import):
                    importados.update(a.name for a in no.names)
                elif isinstance(no, ast.ImportFrom) and no.level == 0:
                    importados.add(no.module or "")
            with self.subTest(modulo=nome):
                self.assertLessEqual(importados, permitidos)

    def test_os_nove_passos_numa_frase(self) -> None:
        saida = norm("Quero, mano, uma GELEIRA LG de 250 litros até 250 mil Kz 😀")
        # 1: minusculas, sem acentos nem emoji; 3: o preco saiu; 4: litros -> l;
        # 7: «quero» e «mano» sairam; 8: o sinonimo so no q_or.
        self.assertEqual(saida.q_norm, "uma geleira lg de 250 l")
        self.assertEqual(saida.restricoes.max_preco_minor, 25_000_000)
        self.assertIn("frigorifico", saida.q_or.split(n.SEPARADOR_OR))
        self.assertNotIn("frigorifico", saida.q_norm)

    def test_origem_fora_da_lista_levanta(self) -> None:
        with self.assertRaises(ValueError):
            norm("geleira", origem="email")


class TestRestricoes(unittest.TestCase):
    """Criterio 2: a tabela do §5.2 como ensaios. Valores em unidade menor."""

    def test_os_tres_maximos(self) -> None:
        for frase in ("até 250 mil", "no máximo 250k", "menos de 250.000 kz"):
            with self.subTest(frase=frase):
                saida = norm("geleira " + frase)
                self.assertEqual(saida.restricoes.como_dict(), {"max_preco_minor": 25_000_000})
                self.assertEqual(saida.q_norm, "geleira")

    def test_entre(self) -> None:
        saida = norm("entre 100 e 150 mil")
        self.assertEqual(
            saida.restricoes.como_dict(),
            {"max_preco_minor": 15_000_000, "min_preco_minor": 10_000_000},
        )

    def test_sem_verbo_e_alvo_e_nao_filtro(self) -> None:
        saida = norm("geleira 250 mil")
        self.assertEqual(saida.restricoes.como_dict(), {"alvo_preco_minor": 25_000_000})
        self.assertIsNone(saida.restricoes.max_preco_minor)

    def test_as_formas_de_aoa(self) -> None:
        for moeda in ("kz", "kwanzas", "akz", "kuanza", "AOA"):
            with self.subTest(moeda=moeda):
                self.assertEqual(norm(f"ate 300 {moeda}").restricoes.max_preco_minor, 30_000)

    def test_outra_moeda_pergunta_e_nao_filtra(self) -> None:
        for frase, codigo in (("até 300 dólares", "USD"), ("ate $300", "USD"), ("até 50 €", "EUR")):
            with self.subTest(frase=frase):
                saida = norm("iphone " + frase)
                self.assertEqual(saida.restricoes.como_dict(), {"moeda": codigo})
                self.assertTrue(saida.precisa_de_pergunta)

    def test_um_numero_sem_multiplicador_nem_moeda_nao_e_preco(self) -> None:
        """«iphone 13», «250 litros», «2 bicicletas»: ficam no texto."""
        for frase in ("iphone 13", "geleira 250 litros", "2 bicicletas", "ate 3 telemoveis"):
            with self.subTest(frase=frase):
                self.assertEqual(norm(frase).restricoes.como_dict(), {})

    def test_o_preco_nunca_chega_ao_texto_de_pesquisa(self) -> None:
        """«NAO vao ao indice»: nem algarismo, nem `mil`, nem moeda, nem verbo."""
        saida = norm("frigorifico no maximo 250 mil kwanzas")
        self.assertEqual(saida.q_norm, "frigorifico")
        self.assertEqual(saida.q_or, "frigorifico")


class TestVoz(unittest.TestCase):
    """Criterio 3: por extenso so com `origem = 'voz'`."""

    def test_duzentos_e_cinquenta_mil(self) -> None:
        self.assertEqual(numeros.valor_por_extenso("duzentos e cinquenta mil"), 250_000)
        saida = norm("duzentos e cinquenta mil", origem="voz")
        self.assertEqual(saida.restricoes.alvo_preco_minor, 250_000 * numeros.MINOR_POR_KZ)

    def test_com_verbo_de_limite(self) -> None:
        saida = norm("geleira até duzentos e cinquenta mil", origem="voz")
        self.assertEqual(saida.restricoes.max_preco_minor, 25_000_000)
        self.assertEqual(saida.q_norm, "geleira")

    def test_so_converte_com_origem_voz(self) -> None:
        saida = norm("duzentos e cinquenta mil", origem="texto")
        self.assertEqual(saida.restricoes.como_dict(), {})
        self.assertIn("cinquenta", saida.q_norm)

    def test_a_tabela_de_numeros(self) -> None:
        casos = {
            "cinco": 5,
            "dezassete": 17,
            "cento e vinte": 120,
            "mil e duzentos": 1_200,
            "dois milhoes e quinhentos mil": 2_500_000,
            "um milhao": 1_000_000,
            "trezentos e quarenta e cinco mil": 345_000,
        }
        for texto, valor in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(numeros.valor_por_extenso(texto), valor)

    def test_o_artigo_nao_e_numero(self) -> None:
        self.assertEqual(numeros.por_extenso("quero um telemovel".split()), ["quero", "um", "telemovel"])


class TestLexicoDosDoisLados(unittest.TestCase):
    """Criterio 4, a metade pura: o que vai ao indice e o que fica na consulta."""

    def test_marca_e_unidade_nos_dois_lados(self) -> None:
        documento = n.normalizar_documento("I Phone 13 128 giga", lexico())
        consulta = norm("ifone 13 128 giga")
        self.assertEqual(documento.nome_norm, "iphone 13 128 gb")
        self.assertEqual(documento.marca_canon, "iphone")
        self.assertEqual(consulta.q_norm, "iphone 13 128 gb")

    def test_sinonimo_so_na_consulta(self) -> None:
        documento = n.normalizar_documento("Geleira Samsung 250 L", lexico())
        self.assertEqual(documento.nome_norm, "geleira samsung 250 l")
        self.assertIn("frigorifico", norm("geleira").q_or.split(n.SEPARADOR_OR))

    def test_unidade_colada_separa_e_o_modelo_nao(self) -> None:
        self.assertEqual(n.normalizar_documento("Geleira 250l", lexico()).nome_norm, "geleira 250 l")
        self.assertEqual(n.normalizar_documento("Samsung A52", lexico()).nome_norm, "samsung a52")
        self.assertEqual(n.normalizar_documento('TV 55"', lexico()).nome_norm, "tv 55 pol")

    def test_sem_lexico_o_documento_e_o_passo_1_do_kam_061(self) -> None:
        """Lexico vazio = o `texto.normalizar` do KAM-061: a versao 1 nao muda."""
        from kamba_core.idx import texto

        for nome in ("Frigorífico LG 250 L", "Nike Air Force 1 Branco", "Arroz 2 kg"):
            with self.subTest(nome=nome):
                self.assertEqual(
                    n.normalizar_documento(nome, n.Lexico(None)).nome_norm, texto.normalizar(nome)
                )


class TestTypo(unittest.TestCase):
    """Criterio 5: tabela de erros comuns, depois vocabulario com limiar 0,6."""

    def test_niker_e_nike(self) -> None:
        saida = norm("niker")
        self.assertEqual(saida.q_norm, "nike")
        self.assertEqual(saida.tokens_nao_resolvidos, ())

    def test_xyzq_nao_se_resolve(self) -> None:
        saida = norm("xyzq")
        self.assertEqual(saida.tokens_nao_resolvidos, ("xyzq",))
        self.assertTrue(saida.precisa_de_pergunta)

    def test_typo_acima_do_limiar_corrige_pelo_vocabulario(self) -> None:
        self.assertGreaterEqual(n.semelhanca("frigorifco", "frigorifico"), n.LIMIAR_DE_CORRECCAO)
        saida = norm("frigorifco")
        self.assertEqual(saida.q_norm, "frigorifico")
        self.assertEqual(saida.correccoes, (("frigorifco", "frigorifico"),))

    def test_abaixo_do_limiar_nao_corrige(self) -> None:
        """«nikr» e «nike» ficam abaixo de 0,6: nada de correccao silenciosa."""
        self.assertLess(n.semelhanca("nikr", "nike"), n.LIMIAR_DE_CORRECCAO)
        saida = norm("nikr")
        self.assertEqual(saida.q_norm, "nikr")
        self.assertEqual(saida.tokens_nao_resolvidos, ("nikr",))

    def test_semelhanca_e_a_do_pg_trgm(self) -> None:
        """Os trigramas com margem do `pg_trgm`: 4 comuns em 7 distintos."""
        self.assertAlmostEqual(n.semelhanca("niker", "nike"), 4 / 7)
        self.assertEqual(n.semelhanca("abc", "abc"), 1.0)
        self.assertEqual(n.semelhanca("", "abc"), 0.0)

    def test_empate_decide_se_pela_frequencia_e_depois_pela_ordem(self) -> None:
        vocabulario = n.Vocabulario.de_frequencias({"bolsa": 1, "bolso": 9})
        self.assertEqual(vocabulario.melhor("bols")[0], "bolso")
        vocabulario = n.Vocabulario.de_frequencias({"bolsa": 3, "bolso": 3})
        self.assertEqual(vocabulario.melhor("bols")[0], "bolsa")

    def test_palavras_funcionais_e_sinonimos_nao_sao_typo(self) -> None:
        saida = norm("geleira de lg para casa")
        self.assertNotIn("de", saida.tokens_nao_resolvidos)
        self.assertNotIn("para", saida.tokens_nao_resolvidos)
        self.assertNotIn("geleira", saida.tokens_nao_resolvidos)

    def test_sem_vocabulario_nao_ha_typo(self) -> None:
        saida = n.normalizar("xyzq", None, "texto", lexico=lexico(), vocabulario=None)
        self.assertEqual(saida.tokens_nao_resolvidos, ())


class TestPrecedencia(unittest.TestCase):
    """Criterio 6, a metade pura: tenant > global, e B nunca em A."""

    LINHAS = (
        {"tenant_id": None, "tipo": "sinonimo", "termo": "bina", "canonico": "bicicleta"},
        {"tenant_id": A, "tipo": "sinonimo", "termo": "bina", "canonico": "motorizada"},
        {"tenant_id": B, "tipo": "marca", "termo": "naiki", "canonico": "nike"},
    )

    def test_o_termo_do_tenant_prevalece(self) -> None:
        saida = n.normalizar("bina", A, "texto", lexico=n.Lexico.de_linhas(self.LINHAS, A))
        self.assertEqual(saida.q_or, "bina or motorizada")

    def test_sem_termo_do_tenant_vale_o_global(self) -> None:
        saida = n.normalizar("bina", B, "texto", lexico=n.Lexico.de_linhas(self.LINHAS, B))
        self.assertEqual(saida.q_or, "bina or bicicleta")

    def test_um_termo_de_b_nunca_se_aplica_a_a(self) -> None:
        lexico_a = n.Lexico.de_linhas(self.LINHAS, A)
        self.assertNotIn(("marca", ("naiki",)), lexico_a.termos)
        self.assertEqual(n.normalizar_documento("Naiki Air", lexico_a).nome_norm, "naiki air")
        self.assertEqual(
            n.normalizar_documento("Naiki Air", n.Lexico.de_linhas(self.LINHAS, B)).nome_norm,
            "nike air",
        )

    def test_lexico_de_outro_tenant_levanta(self) -> None:
        with self.assertRaises(ValueError):
            n.normalizar("bina", A, "texto", lexico=n.Lexico.de_linhas(self.LINHAS, B))

    def test_inactivos_nao_contam(self) -> None:
        linhas = ({"tenant_id": None, "tipo": "sinonimo", "termo": "bina", "canonico": "bicicleta", "activo": False},)
        self.assertEqual(n.Lexico.de_linhas(linhas, A).termos, {})


class TestAmbiguo(unittest.TestCase):
    """Criterio 9: «telefone» pergunta; nao se corrige em silencio."""

    def test_telefone_sozinho_pergunta(self) -> None:
        saida = norm("telefone")
        self.assertEqual(
            saida.desambiguacoes,
            (n.Desambiguacao("telefone", ("telemovel", "telefone fixo")),),
        )
        self.assertNotIn("telemovel", saida.q_or)
        self.assertNotIn("telefone", saida.q_or)
        self.assertTrue(saida.precisa_de_pergunta)

    def test_telefone_fixo_ja_respondeu(self) -> None:
        saida = norm("telefone fixo")
        self.assertEqual(saida.desambiguacoes, ())

    def test_celular_nao_e_ambiguo(self) -> None:
        saida = norm("celular samsung")
        self.assertEqual(saida.desambiguacoes, ())
        self.assertIn("telemovel", saida.q_or.split(n.SEPARADOR_OR))


class TestLatencia(unittest.TestCase):
    """Criterio 10 (proposta): p95 <= 20 ms por consulta, medido aqui.

    Lexico de 2 000 termos e vocabulario de 5 000 palavras, 500 consultas. A
    medicao e numa maquina de desenvolvimento e serve de piso: a do ambiente de
    referencia e a que conta.
    """

    def test_p95_abaixo_de_20_ms(self) -> None:
        linhas = [
            {"tenant_id": None, "tipo": ("sinonimo", "marca", "erro_comum", "unidade")[i % 4],
             "termo": f"termo{i}", "canonico": f"canon{i}"}
            for i in range(2_000)
        ]
        lex = n.Lexico.de_linhas(linhas, None)
        voc = n.Vocabulario.de_frequencias({f"palavra{i}x{i % 97}": i % 13 + 1 for i in range(5_000)})
        frases = ("quero uma geleira lg ate 250 mil", "palavr12x1 termo3 xyzq", "niker air force 1 branco")
        tempos = []
        for i in range(500):
            inicio = time.perf_counter()
            n.normalizar(frases[i % 3], None, "texto", lexico=lex, vocabulario=voc)
            tempos.append((time.perf_counter() - inicio) * 1000)
        p95 = statistics.quantiles(tempos, n=20)[-1]
        self.assertLessEqual(p95, 20.0, f"p95 = {p95:.2f} ms")


if __name__ == "__main__":
    unittest.main()
