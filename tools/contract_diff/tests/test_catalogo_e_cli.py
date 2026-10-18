"""O catalogo real, e o gate como um todo (KAM-007).

Os outros dois ficheiros testam a logica com schemas construidos para o efeito.
Este corre sobre **os trinta e oito contratos do repositorio** e sobre o CLI,
que e o que o `make ci-7` chama. Uma logica certa com um catalogo que nao
carrega nao serve de nada.
"""

from __future__ import annotations

import io
import contextlib
import unittest
from pathlib import Path

from contract_diff import catalogo, cli, exemplos, gerar, pii, subscricoes

RAIZ = Path(__file__).resolve().parents[3]

#: Os trinta e oito **tipos** do dicionario §3.5, emenda 1.11. Escritos aqui a
#: mao e nao lidos do dicionario: se alguem apagar um contrato **e** a linha do
#: dicionario, uma contagem derivada dos dois continuava a bater.
ESPERADOS = 38

#: As versoes publicadas de cada tipo. Sao **duas** desde o KAM-159, que
#: acrescentou a `v2` a todos: a uniao das finalidades de consentimento alarga
#: o dominio do envelope, e alargar um dominio e quebrante (§6.6).
VERSOES_POR_TIPO = 2

#: Os **ficheiros** de contrato. E o que o catalogo devolve, e nao o numero de
#: tipos — distincao que so passou a existir no dia em que nasceu a primeira
#: segunda versao.
ESPERADOS_FICHEIROS = ESPERADOS * VERSOES_POR_TIPO

#: Os oito que o `docs/tecnica/06` §5 **nao** tem, e porque e que estao no
#: catalogo. Esta lista e o complemento exacto do §5: o que nao estiver aqui
#: nem la nao pode ter contrato (ver `TestCoberturaDoCinco`).
FORA_DO_CINCO = {
    "tenant.provisioned": "dicionario §3.5 e specs/EPIC-09 (saga de provisioning)",
    "channel.updated": "dicionario §3.5; o CHR invalida a cache de resolucao",
    "channel.inactivity_warning": "dicionario §3.5 «Tipos do Piloto»",
    "contact.merged": "dicionario §3.5; o KAM-008 funde contactos",
    "conversation.mode_changed": "dicionario §3.5; o HND troca o modo do canal",
    "booking.created": "specs/EPIC-04, vertical de servicos",
    "booking.reminder_due": "specs/EPIC-04, por extenso: «registar no catalogo (KAM-007)»",
    "booking.cancelled": "specs/EPIC-04, vertical de servicos",
}

#: O §5 escreve os tipos de uma familia em abreviatura — `tenant.activated` /
#: `.suspended` — e o prefixo e o que vem antes do primeiro ponto. Numa linha
#: isso nao da o nome certo: `privacy.erasure_requested` / `.applied` quer
#: dizer `privacy.erasure_applied` e nao `privacy.applied`. Corrige-se aqui,
#: a vista, em vez de se inventar uma regra que acerte nos dois — e a
#: ambiguidade do §5 fica registada em `docs/dividas-documentais.md`.
LEITURA_CORRIGIDA = {"privacy.applied": "privacy.erasure_applied"}

#: O padrao que le um tipo de evento, inteiro ou em abreviatura, do §5.
PADRAO_DO_TIPO = r"`(\.?[a-z_]+(?:\.[a-z_]+)?)`"


def _tabela_do_cinco() -> list[list[str]]:
    """As linhas da tabela do `docs/tecnica/06` §5, ja partidas em celulas."""
    caminho = RAIZ / "docs" / "tecnica" / "06_Dados_Eventos_Analytics.md"
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    inicio = next(n for n, l in enumerate(linhas) if l.startswith("## 5. Cat"))
    fim = next(n for n, l in enumerate(linhas[inicio + 1:], inicio + 1) if l.startswith("## "))
    tabela = []
    for linha in linhas[inicio:fim]:
        if not linha.startswith("|"):
            continue
        celulas = [c.strip() for c in linha.strip("|").split("|")]
        if len(celulas) >= 6 and celulas[-1] in ("P", "C", "D"):
            tabela.append(celulas)
    return tabela


def _tipos_da_celula(celula: str) -> list[str]:
    """Os tipos de evento de uma celula, com as abreviaturas expandidas."""
    import re

    prefixo, tipos = None, []
    for token in re.findall(PADRAO_DO_TIPO, celula):
        if token.startswith("."):
            if prefixo:
                nome = prefixo + token
                tipos.append(LEITURA_CORRIGIDA.get(nome, nome))
        elif "." in token:
            prefixo = token.split(".")[0]
            tipos.append(token)
    return tipos


def tipos_do_cinco() -> dict:
    """Os tipos do §5, por fase."""
    por_fase: dict = {"P": set(), "C": set(), "D": set()}
    for celulas in _tabela_do_cinco():
        por_fase[celulas[-1]].update(_tipos_da_celula(celulas[0]))
    return por_fase


def agregado_e_pii_do_cinco() -> dict:
    """Por tipo de Fase P, o que as colunas Agregado e PII do §5 dizem."""
    mapa: dict = {}
    for celulas in _tabela_do_cinco():
        if celulas[-1] != "P":
            continue
        for nome in _tipos_da_celula(celulas[0]):
            mapa[nome] = (celulas[3], celulas[4])
    return mapa


class TestOCatalogoDoRepositorio(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contratos = catalogo.todos(RAIZ)

    def test_sao_trinta_e_oito_e_carregam_todos(self) -> None:
        self.assertEqual(len(self.contratos), ESPERADOS_FICHEIROS)
        self.assertEqual(len({c.tipo for c in self.contratos}), ESPERADOS)

    def test_todos_os_tipos_tem_as_mesmas_versoes(self) -> None:
        """Ate ao KAM-159 todos eram `v1`, e este teste dizia-o.

        Hoje sao `v1` e `v2`, e o que importa e que **nenhum tipo fique para
        tras**: a `v2` alargou o dominio das finalidades no envelope, que e
        comum aos 38, pelo que ou todos a tem ou ha um que o produtor novo nao
        consegue emitir com a finalidade nova.
        """
        esperadas = set(range(1, VERSOES_POR_TIPO + 1))
        por_tipo: dict[str, set[int]] = {}
        for contrato in self.contratos:
            por_tipo.setdefault(contrato.tipo, set()).add(contrato.versao)
        self.assertEqual(len(por_tipo), ESPERADOS)
        for tipo, versoes in sorted(por_tipo.items()):
            with self.subTest(tipo=tipo):
                self.assertEqual(versoes, esperadas)

    def test_cada_versao_tem_o_seu_exemplo(self) -> None:
        """Havia **um** exemplo por pasta, validado contra todas as versoes.

        Enquanto so houve `v1` isso bastou; no dia em que nasceu a `v2`, o
        mesmo ficheiro tinha de dizer `versao: 1` e `versao: 2` ao mesmo tempo.
        """
        for contrato in self.contratos:
            with self.subTest(tipo=contrato.tipo, versao=contrato.versao):
                self.assertTrue(catalogo.exemplo_de(contrato).is_file())

    def test_o_tipo_do_caminho_bate_com_o_const_do_schema(self) -> None:
        for contrato in self.contratos:
            with self.subTest(tipo=contrato.tipo):
                propriedades = contrato.documento["properties"]
                self.assertEqual(propriedades["tipo"]["const"], contrato.tipo)
                self.assertEqual(propriedades["versao"]["const"], contrato.versao)

    def test_todos_tem_os_catorze_campos_de_topo(self) -> None:
        """A emenda 1.11: nem um a mais, nem um a menos."""
        esperados = {
            "id", "tipo", "versao", "tenant_id", "ocorrido_em", "registado_em",
            "produtor", "agregado", "correlacao_id", "causa_id", "trace_id",
            "classe_pii", "finalidades", "payload",
        }
        for contrato in self.contratos:
            with self.subTest(tipo=contrato.tipo):
                self.assertEqual(set(contrato.documento["properties"]), esperados)
                self.assertEqual(set(contrato.documento["required"]), esperados)

    def test_todos_sao_fechados_a_cabeca_e_no_payload(self) -> None:
        """`additionalProperties: false` nos dois niveis (criterio 2)."""
        for contrato in self.contratos:
            with self.subTest(tipo=contrato.tipo):
                self.assertIs(contrato.documento["additionalProperties"], False)
                self.assertIs(contrato.payload["additionalProperties"], False)

    def test_o_dinheiro_e_inteiro_e_a_moeda_e_explicita(self) -> None:
        """Criterio 2: «valores monetarios sao inteiros; moeda explicita»."""
        com_dinheiro = 0
        for contrato in self.contratos:
            propriedades = contrato.payload.get("properties") or {}
            monetarios = [n for n in propriedades if n.endswith("_minor")]
            if not monetarios:
                continue
            com_dinheiro += 1
            with self.subTest(tipo=contrato.tipo):
                for nome in monetarios:
                    tipos = propriedades[nome].get("type")
                    tipos = tipos if isinstance(tipos, list) else [tipos]
                    self.assertIn("integer", tipos, f"{nome} nao e inteiro")
                    self.assertNotIn("number", tipos, f"{nome} aceita virgula flutuante")
                self.assertIn(
                    "currency", propriedades,
                    f"{contrato.tipo} tem dinheiro e nao diz a moeda",
                )
                self.assertEqual(propriedades["currency"]["enum"], ["AOA"])
        self.assertGreaterEqual(com_dinheiro, 6, "o teste deixou de ver os contratos de dinheiro")

    def test_nenhum_nome_de_campo_e_de_pii(self) -> None:
        self.assertEqual([str(a) for a in pii.nomes(RAIZ)], [])

    def test_nenhum_ficheiro_tem_telefone(self) -> None:
        self.assertEqual([str(a) for a in pii.fixtures(RAIZ)], [])

    def test_cada_contrato_tem_exemplo_valido(self) -> None:
        self.assertEqual([str(a) for a in exemplos.validar(RAIZ)], [])
        self.assertEqual([str(a) for a in exemplos.coerencia(RAIZ)], [])


class TestCoberturaDoCinco(unittest.TestCase):
    """O criterio 1 contra a sua fonte, e nao contra um numero.

    O `test_sao_trinta_e_oito_e_carregam_todos` protege a **cardinalidade**:
    apagar o `order.paid` e acrescentar um `foo.bar` deixava-o verde, e o
    criterio 1 nao fala de quantos, fala de **quais** — «100% dos tipos de
    Fase P». Apanhado pela revisao adversarial (achado M4). Aqui le-se a
    tabela do `docs/tecnica/06` §5, filtra-se a coluna Fase, e exige-se
    **igualdade de conjuntos** com o catalogo, com os oito de fora nomeados um
    a um e com a razao de cada um.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.do_cinco = tipos_do_cinco()
        cls.no_catalogo = {c.tipo for c in catalogo.todos(RAIZ)}

    def test_a_tabela_do_cinco_le_se(self) -> None:
        """Se o §5 mudar de forma, isto falha antes de os outros mentirem."""
        self.assertGreaterEqual(len(self.do_cinco["P"]), 25, "a leitura do §5 perdeu linhas")
        self.assertIn("order.created", self.do_cinco["P"])
        self.assertIn("privacy.erasure_applied", self.do_cinco["P"])

    def test_todos_os_de_fase_p_tem_contrato(self) -> None:
        em_falta = self.do_cinco["P"] - self.no_catalogo
        self.assertEqual(em_falta, set(), f"tipos de Fase P sem contrato: {sorted(em_falta)}")

    def test_e_nada_de_fase_c_ou_d_tem_contrato(self) -> None:
        """Um contrato para um evento que ninguem emite e especulacao."""
        adiantados = (self.do_cinco["C"] | self.do_cinco["D"]) & self.no_catalogo
        self.assertEqual(adiantados, set())

    def test_o_catalogo_e_exactamente_o_cinco_mais_os_oito_nomeados(self) -> None:
        self.assertEqual(self.no_catalogo, self.do_cinco["P"] | set(FORA_DO_CINCO))


class TestOQueOCincoFixaPorTipo(unittest.TestCase):
    """O agregado e a classe de PII de cada contrato contra o §5.

    As colunas **Agregado** e **PII** do §5 nao tinham execucao mecanica
    nenhuma (achado M2): o `agregado.tipo` era `{"type": "string"}` livre nos
    trinta e oito, e a `classe_pii` aceitava `P0|P1|P2` em todos. No dia em
    que o `const` entrou, apanhou **vinte e sete exemplos** com
    `agregado.tipo: "order"` copiado da primeira pasta.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.contratos = catalogo.todos(RAIZ)
        cls.do_cinco = agregado_e_pii_do_cinco()

    def test_o_agregado_e_const_em_todos(self) -> None:
        for contrato in self.contratos:
            with self.subTest(tipo=contrato.tipo):
                agregado = contrato.documento["properties"]["agregado"]["properties"]["tipo"]
                self.assertIn("const", agregado, "o agregado ficou livre outra vez")

    def test_e_bate_com_o_cinco_onde_o_cinco_fala(self) -> None:
        falou = 0
        for contrato in self.contratos:
            esperado = self.do_cinco.get(contrato.tipo)
            if esperado is None:
                self.assertIn(contrato.tipo, FORA_DO_CINCO)
                continue
            falou += 1
            agregado, classe = esperado
            with self.subTest(tipo=contrato.tipo):
                propriedades = contrato.documento["properties"]
                self.assertEqual(
                    propriedades["agregado"]["properties"]["tipo"]["const"], agregado
                )
                self.assertEqual(
                    propriedades["classe_pii"]["enum"],
                    ["P0"] if classe == "P0" else ["P0", "P1"],
                )
        self.assertGreaterEqual(falou, 25, "a leitura do §5 perdeu linhas")

    def test_nenhum_contrato_admite_p2(self) -> None:
        """§7.1: «sem PII crua em eventos (P2 proibida)».

        Os trinta e oito admitiam-na (achado M1): a unica verificacao de P2
        incidia sobre o **exemplo**, e um produtor que emitisse `classe_pii`
        igual a `P2` passava o contrato, o `validarPayload` e o gate inteiro.
        """
        for contrato in self.contratos:
            with self.subTest(tipo=contrato.tipo):
                classes = contrato.documento["properties"]["classe_pii"]["enum"]
                self.assertNotIn("P2", classes)


class TestOsDoisPagamentosSaoDistinguiveis(unittest.TestCase):
    """O §5 criou dois eventos para distinguir duas autenticacoes.

    `payment.confirmed` e emitido «**so** por callback autenticado (ADR-013)»;
    `payment.manual_confirmed` e «confirmacao humana auditada». Os dois
    contratos declaravam o **mesmo** objecto `autenticacao`, com os tres
    metodos — e o unico facto que os separava era o nome do tipo (achado M7).
    O DAT, que o §5 manda contar o manual «a parte», nao tinha por onde
    reconciliar.
    """

    def autenticacao(self, tipo: str, versao: int = 1) -> dict:
        # Por versao desde o KAM-159: ha mais do que um contrato por tipo.
        (contrato,) = [
            c for c in catalogo.todos(RAIZ) if c.tipo == tipo and c.versao == versao
        ]
        return contrato.payload["properties"]["autenticacao"]["properties"]

    def test_as_duas_versoes_mantem_a_distincao(self) -> None:
        """A `v2` nao pode ter fundido os dois dominios por descuido: e a
        propriedade que o M7 do KAM-007 custou a ganhar."""
        for versao in range(1, VERSOES_POR_TIPO + 1):
            with self.subTest(versao=versao):
                automatico = set(
                    self.autenticacao("payment.confirmed", versao)["authn_method"]["enum"]
                )
                manual = set(
                    self.autenticacao("payment.manual_confirmed", versao)["authn_method"]["enum"]
                )
                self.assertEqual(automatico & manual, set())

    def test_os_dominios_nao_se_intersectam(self) -> None:
        automatico = set(self.autenticacao("payment.confirmed")["authn_method"]["enum"])
        manual = set(self.autenticacao("payment.manual_confirmed")["authn_method"]["enum"])
        self.assertEqual(automatico & manual, set())
        self.assertEqual(manual, {"manual"})

    def test_um_pagamento_confirmado_tem_authn_ok(self) -> None:
        """«Confirmado» com `authn_ok` falso e uma contradicao em termos."""
        for tipo in ("payment.confirmed", "payment.manual_confirmed"):
            with self.subTest(tipo=tipo):
                self.assertIs(self.autenticacao(tipo)["authn_ok"]["const"], True)


class TestAQualquerProfundidade(unittest.TestCase):
    """O que os testes do criterio 2 viam so no primeiro nivel (achado m5).

    O `order.created.payload.linhas[].preco_minor` era invisivel para eles: o
    dinheiro aninhado podia ser `number` e o objecto aninhado podia estar
    aberto, com os dois testes verdes. Os valores medidos estavam certos; o
    que faltava era o invariante.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.contratos = catalogo.todos(RAIZ)

    def objectos(self, no, caminho="payload"):
        """Todo o subschema de tipo `object`, a qualquer profundidade."""
        if isinstance(no, dict):
            if no.get("type") == "object":
                yield caminho, no
            for nome, filho in (no.get("properties") or {}).items():
                yield from self.objectos(filho, f"{caminho}.{nome}")
            if "items" in no:
                yield from self.objectos(no["items"], f"{caminho}[]")

    def campos(self, no, caminho="payload"):
        if isinstance(no, dict):
            for nome, filho in (no.get("properties") or {}).items():
                yield f"{caminho}.{nome}", nome, filho
                yield from self.campos(filho, f"{caminho}.{nome}")
            if "items" in no:
                yield from self.campos(no["items"], f"{caminho}[]")

    def test_nenhum_objecto_fica_aberto(self) -> None:
        contados = 0
        for contrato in self.contratos:
            for caminho, no in self.objectos(contrato.payload):
                contados += 1
                with self.subTest(tipo=contrato.tipo, onde=caminho):
                    self.assertIs(no.get("additionalProperties"), False)
        self.assertGreater(
            contados, ESPERADOS_FICHEIROS, "ha objectos aninhados e o teste nao os ve"
        )

    def test_nenhum_dinheiro_e_virgula_flutuante(self) -> None:
        monetarios = 0
        for contrato in self.contratos:
            for caminho, nome, no in self.campos(contrato.payload):
                if not nome.endswith("_minor"):
                    continue
                monetarios += 1
                tipos = no.get("type")
                tipos = tipos if isinstance(tipos, list) else [tipos]
                with self.subTest(tipo=contrato.tipo, onde=caminho):
                    self.assertIn("integer", tipos)
                    self.assertNotIn("number", tipos)
        self.assertGreaterEqual(monetarios, 7, "o teste deixou de ver o dinheiro aninhado")

    def test_nenhum_number_em_lado_nenhum(self) -> None:
        """Nao so nos `*_minor`: `number` nao tem uso nestes contratos."""
        for contrato in self.contratos:
            for caminho, _nome, no in self.campos(contrato.payload):
                tipos = no.get("type")
                tipos = tipos if isinstance(tipos, list) else [tipos]
                with self.subTest(tipo=contrato.tipo, onde=caminho):
                    self.assertNotIn("number", tipos)


class TestOGerador(unittest.TestCase):
    """O que o gerador escreve, verificado no texto que ele escreve.

    Estas quatro nasceram de **mutacoes sobreviventes**: a prova por mutacao
    da *suite* `contratos` matou o `NotRequired`, matou a deteccao do campo a
    mais no validador Python e abriu a guarda de palavras-chave, e os
    dezassete testes que havia ficaram todos verdes. Os testes que provavam
    as duas primeiras existiam — no `libs/py-core`, que e outra *suite* e que
    esta prova nao corre. Um invariante provado noutra bateria nao protege o
    ficheiro que o gera.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.contratos = catalogo.todos(RAIZ)
        cls.py = gerar.python(cls.contratos)

    def test_o_opcional_sai_com_not_required(self) -> None:
        self.assertIn("NotRequired[", self.py)
        self.assertIn("expira_at: NotRequired[str]", self.py)

    def test_o_obrigatorio_sai_sem_not_required(self) -> None:
        self.assertIn("    order_id: str\n", self.py)
        self.assertNotIn("total=False", self.py)

    def test_o_validador_python_ve_o_campo_a_mais(self) -> None:
        """Nao basta o validador existir: tem de recusar o que sobra."""
        espaco: dict = {}
        exec(compile(self.py, "<gerado>", "exec"), espaco)
        with self.assertRaises(espaco["PayloadInvalidoError"]) as apanhado:
            espaco["validar_payload"]("tenant.activated", 1, {"inventado": 1})
        self.assertIn("sobram", str(apanhado.exception))

    def test_o_validador_python_ve_o_obrigatorio_em_falta(self) -> None:
        espaco: dict = {}
        exec(compile(self.py, "<gerado>", "exec"), espaco)
        with self.assertRaises(espaco["PayloadInvalidoError"]) as apanhado:
            espaco["validar_payload"]("order.paid", 1, {})
        self.assertIn("faltam", str(apanhado.exception))

    def test_recusa_uma_palavra_chave_que_nao_sabe_traduzir(self) -> None:
        """O gerador falha ruidoso em vez de emitir um tipo errado.

        A mutacao que abre esta guarda sobrevivia: o `PALAVRAS_SUPORTADAS`
        existia e nenhum teste o exercitava. Um `oneOf` que entrasse num
        contrato gerava um tipo que **nao** descreve o schema, e isso e pior
        do que nao gerar nada, porque o compilador passa a aprovar codigo
        errado com confianca.
        """
        with self.assertRaises(gerar.NaoSeiTraduzirError) as apanhado:
            gerar._verificar({"type": "object", "oneOf": [{}]}, "(ensaio)")
        self.assertIn("oneOf", str(apanhado.exception))

    def test_os_trinta_e_oito_passam_na_guarda(self) -> None:
        """A guarda so vale se o catalogo real a atravessar."""
        for contrato in self.contratos:
            with self.subTest(tipo=contrato.tipo):
                gerar._verificar(contrato.documento, contrato.relativo)


class TestCoerenciaDosExemplos(unittest.TestCase):
    """A `exemplos.coerencia` exercitada em si mesma.

    O `test_cada_contrato_tem_exemplo_valido` corre-a sobre os trinta e oito,
    onde ela nao tem nada a dizer — e por isso a mutacao que desligava a
    verificacao de P2 sobrevivia. Uma funcao so testada pelo caminho em que
    devolve vazio nao esta testada.
    """

    def ficheiros(self, exemplo: dict) -> Path:
        import json
        import shutil
        import tempfile

        raiz = Path(tempfile.mkdtemp(prefix="kamba-exemplo-"))
        self.addCleanup(lambda: shutil.rmtree(raiz, ignore_errors=True))
        pasta = raiz / catalogo.PASTA / "order.paid"
        pasta.mkdir(parents=True)
        original = RAIZ / catalogo.PASTA / "order.paid"
        shutil.copy(original / "v1.schema.json", pasta / "v1.schema.json")
        (pasta / "exemplo.json").write_text(
            json.dumps(exemplo, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return raiz

    def exemplo_bom(self) -> dict:
        import json

        return json.loads(
            (RAIZ / catalogo.PASTA / "order.paid" / "exemplo.json").read_text(encoding="utf-8")
        )

    def test_o_exemplo_do_repositorio_e_coerente(self) -> None:
        self.assertEqual(exemplos.coerencia(self.ficheiros(self.exemplo_bom())), [])

    def test_um_exemplo_com_classe_pii_p2_e_achado(self) -> None:
        exemplo = self.exemplo_bom()
        exemplo["classe_pii"] = "P2"
        (achado,) = exemplos.coerencia(self.ficheiros(exemplo))
        self.assertIn("P2", achado.porque)

    def test_um_exemplo_com_o_tipo_de_outra_pasta_e_achado(self) -> None:
        exemplo = self.exemplo_bom()
        exemplo["tipo"] = "order.created"
        (achado,) = exemplos.coerencia(self.ficheiros(exemplo))
        self.assertIn("a pasta diz", achado.porque)

    def test_um_exemplo_com_a_versao_errada_e_achado(self) -> None:
        exemplo = self.exemplo_bom()
        exemplo["versao"] = 2
        (achado,) = exemplos.coerencia(self.ficheiros(exemplo))
        self.assertIn("o nome do ficheiro diz", achado.porque)

    def test_um_exemplo_com_o_agregado_errado_falha_na_validacao(self) -> None:
        """A verificacao que a docstring prometia e que hoje vive no schema."""
        exemplo = self.exemplo_bom()
        exemplo["agregado"]["tipo"] = "tenant"
        (achado,) = exemplos.validar(self.ficheiros(exemplo))
        self.assertIn("agregado", achado.porque)


class TestSubscricoesVazias(unittest.TestCase):
    """A verificacao que hoje passa sobre um conjunto vazio, e di-lo."""

    def test_nao_ha_subscricoes_declaradas(self) -> None:
        """Se isto falhar, o KAM-038 chegou — e o teste de cima passa a morder."""
        self.assertEqual(subscricoes.ler(RAIZ), [])

    def test_mas_a_verificacao_morde_com_uma_inventada(self) -> None:
        inventada = [subscricoes.Subscricao("(teste)", "ensaio", "order.created", 99)]
        (achado,) = subscricoes.verificar(RAIZ, inventada)
        self.assertIn("versao_max=99", achado.porque)
        # As versoes que existem, e nao um literal: desde o KAM-159 sao duas,
        # e um numero a mao envelhecia na terceira.
        esperadas = sorted(range(1, VERSOES_POR_TIPO + 1))
        self.assertIn(str(esperadas), achado.porque)

    def test_e_morde_um_tipo_que_nao_existe(self) -> None:
        inventada = [subscricoes.Subscricao("(teste)", "ensaio", "nao.existe", 1)]
        (achado,) = subscricoes.verificar(RAIZ, inventada)
        self.assertIn("nao tem contrato nenhum", achado.porque)


class TestCli(unittest.TestCase):
    def correr(self, *argumentos: str) -> tuple[int, str]:
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = cli.main(["--root", str(RAIZ), *argumentos])
        return codigo, saida.getvalue()

    def test_o_canario_prova_que_as_cinco_mordem(self) -> None:
        codigo, texto = self.correr("canario")
        self.assertEqual(codigo, cli.SAIDA_OK, texto)
        self.assertIn("0 falha(s)", texto)

    def test_o_canario_cobre_a_quinta_verificacao(self) -> None:
        """Um `return []` em `dominios.verificar` tem de ser apanhado.

        O KAM-159 acrescentou a quinta verificacao ao gate 7 e **nao** ao
        canario, que ficou a provar quatro de cinco. Foi a revisao adversarial
        que o apanhou (achado M5), e o buraco e exactamente o que o canario
        existe para nao ter: desligar a verificacao nova deixava o CI verde.

        Este teste e o canario do canario, e nao a sua contagem: pinar «11
        negativas» cimentava o numero de hoje e nao dizia **o que** cada uma
        morde.
        """
        from unittest import mock

        with mock.patch.object(cli.dominios, "verificar", return_value=[]):
            codigo, texto = self.correr("canario")
        self.assertEqual(codigo, cli.SAIDA_ACHADOS, texto)
        self.assertIn("enum com um valor que o canon nao tem", texto)
        self.assertIn("envelope sem `enum` nenhum", texto)

    def test_o_lint_de_pii_esta_conforme(self) -> None:
        codigo, texto = self.correr("pii")
        self.assertEqual(codigo, cli.SAIDA_OK, texto)
        self.assertIn(f"{ESPERADOS_FICHEIROS} contrato(s)", texto)

    def test_os_exemplos_validam(self) -> None:
        codigo, texto = self.correr("exemplos")
        self.assertEqual(codigo, cli.SAIDA_OK, texto)

    def test_as_subscricoes_dizem_que_sao_zero(self) -> None:
        """Zero e um numero visivel, e nao um silencio."""
        codigo, texto = self.correr("subscricoes")
        self.assertEqual(codigo, cli.SAIDA_OK, texto)
        self.assertIn("0 subscricoes declaradas", texto)

    def test_sem_base_diz_que_nao_correu(self) -> None:
        """Uma verificacao que se desliga tem de o dizer na saida."""
        codigo, texto = self.correr("--sem-base", "diff")
        self.assertEqual(codigo, cli.SAIDA_OK)
        self.assertIn("**nao correu**", texto)

    def test_uma_base_que_nao_existe_e_erro_de_ambiente_e_nao_silencio(self) -> None:
        codigo, texto = self.correr("--base", "nao/existe/de/certeza", "diff")
        self.assertEqual(codigo, cli.SAIDA_ERRO, texto)
        self.assertIn("fetch-depth", texto)


if __name__ == "__main__":
    unittest.main()
