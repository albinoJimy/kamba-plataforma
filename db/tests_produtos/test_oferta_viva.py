"""O contrato de leitura da oferta viva: a `v_oferta_viva` (KAM-051).

O que esta suite prova e a revisao `0037` — as nove colunas do criterio 1, o
predicado do criterio 2, o `stock_modo` do criterio 3, o `security_invoker` e a
RLS herdada do criterio 4, o contrato de saida da tool do criterio 5 e o plano
de execucao do criterio 6 — e a **leitura composta** do `docs/tecnica/05` secao
6.3, que e o que o indice corre de facto.

## Porque e que quase todos os casos medem a leitura e nao a coluna

Uma vista correcta ligada ao sitio errado passa todos os ensaios dela. O
`product_ref` desta vista **e** o `sku`, e um ensaio que lesse
`SELECT product_ref FROM v_oferta_viva` ficava verde se alguem o trocasse pelo
`medusa_variant_id` — os dois sao `text` e os dois saem na coluna certa. O que
morre com a troca e o **join** por `(tenant_id, product_ref)` contra os
candidatos do indice, porque o `medusa_variant_id` e nulo em toda a Fase 0 e
nenhuma linha casa. Por isso o caso que prova o `product_ref` e o que corre a
consulta da secao 6.3, e nao o que le a coluna.

O mesmo vale para o `publicado`: a coluna e um booleano, e um ensaio que
afirmasse `publicado = false` para um produto pausado continuava verde se o
predicado perdesse a conjuncao do `deleted_at` ou da `categoria_restrita` — basta
que o `estado` sozinho de a resposta certa **naquele** caso. Por isso as tres
condicoes medem-se **uma a uma, cada uma com as outras duas satisfeitas**, que e
a unica forma de a conjuncao ser necessaria.

## O que esta suite nao mede, e porque

**Nada de stock.** O criterio 7 esta bloqueado por decisao aberta (o D3 nao esta
ratificado e o nivel de stock nao existe — a `offer_terms` tem `stock_modo` e
`stock_verificado_at` e nenhuma quantidade, e quem produz as reservas e o
KAM-045, aberto). Logo a vista nao tem `stock_disp`, e a consulta da secao 6.3
corre aqui **sem** o filtro `v.stock_disp > 0`, que nao tem coluna contra que
correr. O caso `test_a_vista_nao_tem_coluna_de_stock` afirma a ausencia, para
que o dia em que a projeccao chegar nao a deixe entrar sem ninguem decidir o
nome.

**Nada de `disponivel`.** E o campo do contrato de saida da tool que depende do
nivel de stock, e fica bloqueado com o criterio 7. O
`test_o_contrato_da_secao_6_3_e_o_que_a_vista_entrega` mede os sete campos que
nao dependem dele e **nomeia** o oitavo, lido do proprio documento.

**Nada de `precoDisplay` nem do texto de `disponibilidade`.** Sao funcao pura e
medem-se em `services/com/tests/produtos.formato.test.ts`, sem base de dados —
pela razao que o `base.py` desta suite ja escreveu.
"""

from __future__ import annotations

import datetime
import re
import unittest
from pathlib import Path

import bootstrap
import ligacao
from tests.base import alembic_ok, em_head, exigir_base_descartavel
from tests_produtos.base import PRECO, SKU_PARTILHADO, ComOfertas, daqui_a

#: As nove colunas do criterio 1, **pela ordem em que a vista as projecta**.
#:
#: A ordem conta: o contrato e consumido por posicao por quem escreve
#: `SELECT v.*`, e uma vista que reordenasse colunas com os mesmos nomes era uma
#: alteracao de contrato que nenhum ensaio de conjunto apanhava.
COLUNAS = (
    "tenant_id",
    "product_ref",
    "sku",
    "nome",
    "preco_minor",
    "preco_tipo",
    "stock_modo",
    "publicado",
    "lido_em",
)

#: O documento que **declara** o contrato de saida da tool. Nao se copia: le-se.
DOC_INDICE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "tecnica"
    / "05_Indice_Pesquisa_Motor_Atencao.md"
)

#: A consulta da secao 6.3, **sem o filtro de stock** e com o `idx.candidatos`
#: substituido por um duplo: o esquema `idx` e do KAM-061 e nao existe.
#:
#: O duplo e um `VALUES` e nao uma tabela de ensaio, de proposito: o que esta
#: suite quer provar e o **join** a oferta viva e a ordenacao, nao o indice. Um
#: `idx.candidatos` falso com a forma certa provava o duplo.
#:
#: O `NULLS LAST` esta escrito e nao implicito. Em PostgreSQL um `ASC` ja poe os
#: nulos no fim, mas o que a secao 6.3 ordena e `v.preco_minor ASC` sobre uma
#: coluna que o `sob_consulta` deixa **nula** — escrever o `NULLS LAST` diz que
#: a escolha foi feita, e protege de um `DESC` futuro que a invertia em silencio.
LEITURA_DO_INDICE = """
    SELECT c.o_product_ref, c.o_score, v.sku, v.nome, v.preco_minor, v.preco_tipo
      FROM (VALUES {candidatos}) AS c(o_product_ref, o_score)
      JOIN platform.v_oferta_viva v
        ON v.tenant_id = %s AND v.product_ref = c.o_product_ref
     WHERE v.publicado
     ORDER BY c.o_score DESC, v.preco_minor ASC NULLS LAST
     LIMIT 3
"""


def _leitura(candidatos: tuple[tuple[str, float], ...]) -> str:
    """A consulta da secao 6.3 com um conjunto de candidatos dado."""
    linhas = ", ".join(f"('{ref}'::text, {score}::float8)" for ref, score in candidatos)
    return LEITURA_DO_INDICE.format(candidatos=linhas)


#: As cinco formas de uma oferta **nao** ser publicavel, uma por condicao da
#: conjuncao do criterio 2 — e o `estado` entra com **dois** dos seus quatro
#: valores, nao com um.
#:
#: **O `rascunho` e o que faltava, e era o que mais faltava.** A primeira versao
#: desta lista tinha `pausado`, `arquivado`, restrito e apagado, e a revisao
#: adversarial mediu o que isso deixava passar: o `rascunho` e a **omissao** do
#: `offer_terms.estado` (`DEFAULT 'rascunho'`, revisao `0028`), isto e, o estado
#: de toda a oferta que o dono comecou e nunca publicou. Com ele de fora, trocar
#: o predicado para `o.estado IN ('publicado','rascunho')` — ou para
#: `o.estado <> 'pausado'` — deixava **as 25 asercoes verdes** e punha o agente a
#: oferecer rascunhos com preco.
CASOS_NAO_PUBLICAVEIS = (
    ("rascunho", {"estado": "rascunho"}),
    ("pausado", {"estado": "pausado"}),
    ("arquivado", {"estado": "arquivado"}),
    ("restrito", {"categoria_restrita": "farmacia"}),
    ("apagado", {"deleted_at": daqui_a(horas=-1)}),
)


class TestContratoDaVista(ComOfertas):
    """As nove colunas, os tipos e os dominios (criterios 1, 3 e 8)."""

    def test_as_nove_colunas_estao_na_ordem_do_contrato(self) -> None:
        """Criterio 1: os nove nomes canonicos do dicionario secao 3.3.

        Pelo `information_schema`, que e a mesma fonte que o inventario fechado
        de `db/tests/test_inventario.py` usa — e nao por um `SELECT *`, que
        devolvia a ordem mas nao provava que nao ha uma decima coluna.
        """
        colunas = self.consultar(
            "SELECT column_name FROM information_schema.columns "
            " WHERE table_schema = 'platform' AND table_name = 'v_oferta_viva' "
            " ORDER BY ordinal_position"
        )
        self.assertEqual(tuple(str(c[0]) for c in colunas), COLUNAS)

    def test_a_vista_nao_tem_coluna_de_stock(self) -> None:
        """Criterio 7, **bloqueado**: a ausencia e que e a entrega.

        O D3 nao esta ratificado e a projeccao de nivel de stock nao existe. Este
        caso nao celebra a falta — fixa-a, para que a projeccao do KAM-045 nao
        entre com um nome que ninguem decidiu. O dia em que entrar, este caso
        falha e **tem** de falhar: e o sinal de que o criterio 7 voltou a mesa.
        """
        colunas = {
            str(c[0])
            for c in self.consultar(
                "SELECT column_name FROM information_schema.columns "
                " WHERE table_schema = 'platform' AND table_name = 'v_oferta_viva'"
            )
        }
        self.assertNotIn("stock_disp", colunas)
        self.assertEqual([c for c in colunas if "stock" in c], ["stock_modo"])

    def test_a_vista_nao_tem_coluna_disponibilidade(self) -> None:
        """Criterio 3: o nome foi gasto pelo KAM-043, com outro dominio.

        Desde a emenda 1.52 e o `DISPONIBILIDADE` de
        `services/com/src/produtos/formato.ts`, `disponibilidade` e **texto de
        apresentacao** em tres valores. Duplicar o mapeamento em SQL dava duas
        respostas para a mesma pergunta.
        """
        colunas = {
            str(c[0])
            for c in self.consultar(
                "SELECT column_name FROM information_schema.columns "
                " WHERE table_schema = 'platform' AND table_name = 'v_oferta_viva'"
            )
        }
        self.assertNotIn("disponibilidade", colunas)

    def test_nao_ha_coluna_de_dinheiro_em_kwanzas(self) -> None:
        """Criterio 1: sem `preco_kz`, e a asercao e sobre a **forma**.

        O `test_nao_ha_colunas_de_dinheiro_nem_saldos` do `db/tests/` ja varre o
        esquema todo; este caso diz a mesma coisa sobre esta vista, no sitio onde
        quem a muda esta a olhar. O `preco_minor` esta declarado no
        `EM_UNIDADE_MENOR`, que e o preco de a vista nascer no `platform`.
        """
        colunas = {
            str(c[0])
            for c in self.consultar(
                "SELECT column_name FROM information_schema.columns "
                " WHERE table_schema = 'platform' AND table_name = 'v_oferta_viva'"
            )
        }
        self.assertEqual([c for c in colunas if c.endswith("_kz")], [])
        self.assertIn("preco_minor", colunas)

    def test_o_dominio_do_stock_modo_e_o_canonico_em_tres_valores(self) -> None:
        """Criterio 3: `garantido`, `indicativo`, `confirmar_dono`.

        A vista nao poe `CHECK` nenhum — herda o `offer_terms_stock_modo_ck`. O
        que este caso prova e que os tres **passam pela vista**, um a um: um
        `CASE` indevido no caminho do `stock_modo` (a tentacao de derivar o texto
        de apresentacao aqui) colapsava-os e este caso morria.
        """
        tenant = self.criar_tenant()
        for modo in ("garantido", "indicativo", "confirmar_dono"):
            with self.subTest(modo=modo):
                sku = self.criar_oferta(tenant, sku=f"sku-{modo}", stock_modo=modo)
                saida = self.consultar(
                    "SELECT stock_modo FROM platform.v_oferta_viva "
                    " WHERE tenant_id = %s AND sku = %s",
                    (tenant, sku),
                )
                self.assertEqual(saida, [(modo,)])


class TestPrecoQueDegrada(ComOfertas):
    """A regra 2 do `docs/tecnica/03` secao 7.1, aplicada na leitura."""

    def test_um_fixo_fora_de_validade_sai_como_a_partir_de(self) -> None:
        """O preco **le-se** como `a_partir_de`; a coluna guardada nao muda.

        As duas metades: o que a vista entrega e o que a tabela continua a
        guardar. Sem a segunda, uma implementacao que escrevesse na tabela
        passava este caso e perdia o que o dono escolheu.
        """
        tenant = self.criar_tenant()
        sku = self.criar_oferta(
            tenant,
            sku="fixo-caducado",
            preco_tipo="fixo",
            preco_valido_ate=daqui_a(horas=-1),
        )
        self.assertEqual(
            self.consultar(
                "SELECT preco_tipo, preco_minor FROM platform.v_oferta_viva "
                " WHERE tenant_id = %s AND sku = %s",
                (tenant, sku),
            ),
            [("a_partir_de", PRECO)],
        )
        self.assertEqual(
            self.consultar(
                "SELECT preco_tipo FROM platform.offer_terms "
                " WHERE tenant_id = %s AND sku = %s",
                (tenant, sku),
            ),
            [("fixo",)],
        )

    def test_um_fixo_dentro_da_validade_sai_fixo(self) -> None:
        """O controlo positivo. Sem ele, um `CASE` sempre verdadeiro passava."""
        tenant = self.criar_tenant()
        sku = self.criar_oferta(
            tenant,
            sku="fixo-valido",
            preco_tipo="fixo",
            preco_valido_ate=daqui_a(horas=24),
        )
        self.assertEqual(
            self.consultar(
                "SELECT preco_tipo FROM platform.v_oferta_viva "
                " WHERE tenant_id = %s AND sku = %s",
                (tenant, sku),
            ),
            [("fixo",)],
        )

    def test_um_fixo_sem_validade_nenhuma_sai_fixo(self) -> None:
        """`preco_valido_ate` nulo nao e «caducado».

        Um `CASE` que comparasse sem guardar o nulo devolvia `NULL` e a coluna
        saia vazia — nem `fixo` nem `a_partir_de`, que e pior do que as duas.
        """
        tenant = self.criar_tenant()
        sku = self.criar_oferta(tenant, sku="fixo-sem-prazo", preco_valido_ate=None)
        self.assertEqual(
            self.consultar(
                "SELECT preco_tipo FROM platform.v_oferta_viva "
                " WHERE tenant_id = %s AND sku = %s",
                (tenant, sku),
            ),
            [("fixo",)],
        )

    def test_um_sob_consulta_caducado_nao_passa_a_a_partir_de(self) -> None:
        """**A guarda que a nota do modulo explica**, e o caso que a prova.

        Um `sob_consulta` tem `preco_minor` nulo por `offer_terms_preco_ck`.
        Devolve-lo como `a_partir_de` afirmava um minimo que ninguem cotou — o
        mesmo defeito que aquele `CHECK` recusa do outro lado, e o que o
        validador de citacao do KAM-032 leria como numero citavel. Sem a guarda
        `preco_tipo = 'fixo'` no `CASE`, este caso morre.
        """
        tenant = self.criar_tenant()
        sku = self.criar_oferta(
            tenant,
            sku="sob-consulta-caducado",
            preco_tipo="sob_consulta",
            preco_minor=None,
            preco_valido_ate=daqui_a(horas=-1),
        )
        self.assertEqual(
            self.consultar(
                "SELECT preco_tipo, preco_minor FROM platform.v_oferta_viva "
                " WHERE tenant_id = %s AND sku = %s",
                (tenant, sku),
            ),
            [("sob_consulta", None)],
        )

    def test_um_a_partir_de_caducado_continua_a_partir_de(self) -> None:
        """Ja e o que a regra manda ler: nao ha degradacao a fazer."""
        tenant = self.criar_tenant()
        sku = self.criar_oferta(
            tenant,
            sku="minimo-caducado",
            preco_tipo="a_partir_de",
            preco_valido_ate=daqui_a(horas=-1),
        )
        self.assertEqual(
            self.consultar(
                "SELECT preco_tipo FROM platform.v_oferta_viva "
                " WHERE tenant_id = %s AND sku = %s",
                (tenant, sku),
            ),
            [("a_partir_de",)],
        )


class TestPublicado(ComOfertas):
    """O criterio 2, e a conjuncao medida uma condicao a uma vez."""

    def test_uma_oferta_publicada_e_limpa_sai_publicada(self) -> None:
        """O controlo positivo, e vem primeiro: sem ele os negativos nao dizem
        nada — quatro falsos contra uma vista vazia nao provam predicado nenhum.
        """
        tenant = self.criar_tenant()
        sku = self.criar_oferta(tenant, estado="publicado")
        self.assertEqual(
            self.consultar(
                "SELECT publicado FROM platform.v_oferta_viva "
                " WHERE tenant_id = %s AND sku = %s",
                (tenant, sku),
            ),
            [(True,)],
        )

    def test_cada_condicao_sozinha_tira_o_publicado(self) -> None:
        """**As tres condicoes, uma a uma, com as outras duas satisfeitas.**

        E a unica forma de a conjuncao ser necessaria: um predicado que
        esquecesse o `deleted_at` continuava a dar a resposta certa para um
        produto pausado, e um ensaio que variasse duas condicoes de uma vez nao
        distinguia qual delas morde.
        """
        tenant = self.criar_tenant()
        for nome, mudanca in CASOS_NAO_PUBLICAVEIS:
            with self.subTest(caso=nome):
                sku = self.criar_oferta(tenant, sku=f"sku-{nome}", **mudanca)
                self.assertEqual(
                    self.consultar(
                        "SELECT publicado FROM platform.v_oferta_viva "
                        " WHERE tenant_id = %s AND sku = %s",
                        (tenant, sku),
                    ),
                    [(False,)],
                    f"{nome}: a condicao nao entra na conjuncao do publicado",
                )

    def test_a_leitura_do_indice_devolve_zero_linhas_para_cada_uma(self) -> None:
        """A segunda metade do criterio 2: «devolve **0 linhas**».

        E aqui que ela e verdadeira, e nao na vista: quem filtra e o
        `WHERE v.publicado` da secao 6.3. Este caso corre a leitura composta,
        que e o que o indice corre de facto — e e o caso que morre se alguem
        tirar o filtro da consulta **ou** a condicao do predicado.
        """
        tenant = self.criar_tenant()
        for nome, mudanca in CASOS_NAO_PUBLICAVEIS:
            with self.subTest(caso=nome):
                sku = self.criar_oferta(tenant, sku=f"ind-{nome}", **mudanca)
                self.assertEqual(
                    self.consultar(_leitura(((sku, 0.9),)), (tenant,)),
                    [],
                    f"{nome}: chegou ao indice",
                )

    def test_a_leitura_do_indice_devolve_a_oferta_limpa(self) -> None:
        """O controlo positivo da leitura composta, com o mesmo instrumento."""
        tenant = self.criar_tenant()
        sku = self.criar_oferta(tenant, sku="ind-limpo", nome="arroz 5 kg")
        self.assertEqual(
            self.consultar(_leitura(((sku, 0.9),)), (tenant,)),
            [(sku, 0.9, sku, "arroz 5 kg", PRECO, "fixo")],
        )


class TestLeituraDoIndice(ComOfertas):
    """A consulta da secao 6.3: o *join*, a ordenacao e o contrato de saida."""

    def test_o_join_e_por_product_ref_e_nao_pelo_id_do_registo(self) -> None:
        """**O caso que mata a troca do `product_ref`.**

        O `product_ref` desta vista e o `sku`. Se alguem o trocar pelo
        `medusa_variant_id` — mesmo tipo, mesma coluna, mesmo nome —, a coluna
        continua a existir e a ler-se, mas o *join* do indice deixa de casar:
        aquele id e **nulo em toda a Fase 0**. Este caso semeia uma oferta com
        `medusa_variant_id` preenchido e **diferente** do `sku`, e exige que o
        candidato que casa seja o do `sku`.
        """
        tenant = self.criar_tenant()
        sku = self.criar_oferta(tenant, sku="arroz-5kg")
        self.semente.execute(
            "UPDATE platform.offer_terms SET medusa_variant_id = %s "
            " WHERE tenant_id = %s AND sku = %s",
            ("variant_do_registo", tenant, sku),
        )
        # Pelo `sku`: casa.
        self.assertEqual(
            [linha[0] for linha in self.consultar(_leitura(((sku, 0.9),)), (tenant,))],
            [sku],
        )
        # Pelo id do Registo: **nao** casa. Se casasse, o `product_ref` era o id.
        self.assertEqual(
            self.consultar(_leitura((("variant_do_registo", 0.9),)), (tenant,)),
            [],
        )

    def test_o_sob_consulta_ordena_no_fim_e_nao_desaparece(self) -> None:
        """Duas coisas de uma vez, e as duas estao nos Detalhes Tecnicos.

        O `NULLS LAST`: um `sob_consulta` tem `preco_minor` nulo e tem de
        ordenar **depois** dos que tem numero, com o mesmo `o_score`. E nao
        desaparece: «e modo de preco e nao de stock», pelo que nenhum filtro o
        tira — o que o tirava era o `v.stock_disp > 0` da secao 6.3, que esta
        vista nao tem e que o criterio 3 manda registar para o KAM-061.
        """
        tenant = self.criar_tenant()
        barato = self.criar_oferta(tenant, sku="barato", preco_minor=100)
        caro = self.criar_oferta(tenant, sku="caro", preco_minor=900)
        opaco = self.criar_oferta(
            tenant, sku="opaco", preco_tipo="sob_consulta", preco_minor=None
        )
        saida = self.consultar(
            _leitura(((barato, 0.5), (caro, 0.5), (opaco, 0.5))), (tenant,)
        )
        self.assertEqual([linha[0] for linha in saida], [barato, caro, opaco])

    def test_o_score_do_indice_manda_antes_do_preco(self) -> None:
        """`ORDER BY c.o_score DESC, v.preco_minor ASC`: a ordem das chaves.

        Um ensaio com um so `o_score` nao distinguia as duas chaves de ordenacao
        — e uma implementacao que ordenasse so por preco passava-o.
        """
        tenant = self.criar_tenant()
        caro_relevante = self.criar_oferta(tenant, sku="caro-rel", preco_minor=900)
        barato_irrelevante = self.criar_oferta(tenant, sku="barato-irr", preco_minor=100)
        saida = self.consultar(
            _leitura(((caro_relevante, 0.9), (barato_irrelevante, 0.1))), (tenant,)
        )
        self.assertEqual(
            [linha[0] for linha in saida], [caro_relevante, barato_irrelevante]
        )

    def test_o_contrato_da_secao_6_3_e_o_que_a_vista_entrega(self) -> None:
        """Criterio 5: o contrato de saida da tool, **lido do documento**.

        Nao e uma copia. Uma copia prova que a copia funciona — a licao que o
        `consultas.py` desta suite escreveu. O documento declara oito campos;
        sete saem desta vista e o oitavo (`disponivel`) depende do nivel de
        stock e fica bloqueado com o criterio 7. O `fonte:'registo'` e uma
        constante do contrato e nao uma coluna.

        Se alguem emendar o contrato na secao 6.3, este caso nota.
        """
        texto = DOC_INDICE.read_text(encoding="utf-8")
        # O documento escreve «saída» com acento. O `[ií]` cobre as duas formas:
        # uma correccao ortografica num documento nao deve calar este caso.
        achado = re.search(r"Contrato de sa[ií]da da tool:\s*`\[\{([^}]*)\}", texto)
        self.assertIsNotNone(achado, "o contrato nao esta na secao 6.3 na forma lida")
        assert achado is not None  # para o verificador de tipos
        # `strip()` **antes** do `split(" ")`: os campos vem separados por «, » e
        # sem isto o espaco a esquerda dava o primeiro pedaco vazio. O
        # `split(":")` tira o valor do `fonte:'registo'`, e o `split(" ")` tira o
        # dominio escrito ao lado do `preco_tipo`.
        campos = {
            parte.strip().split(":")[0].split(" ")[0].strip("`")
            for parte in achado.group(1).split(",")
            if parte.strip()
        }
        # Os oito do documento, e nao menos: se o documento mudar, muda aqui.
        self.assertEqual(
            campos,
            {
                "sku",
                "product_ref",
                "nome",
                "preco_minor",
                "preco_tipo",
                "disponivel",
                "fonte",
                "lido_em",
            },
        )
        # Sete saem da vista. O `fonte` e constante e o `disponivel` esta
        # bloqueado — e e **nomeado** aqui para que o desbloqueio o encontre.
        da_vista = campos - {"fonte", "disponivel"}
        colunas = {
            str(c[0])
            for c in self.consultar(
                "SELECT column_name FROM information_schema.columns "
                " WHERE table_schema = 'platform' AND table_name = 'v_oferta_viva'"
            )
        }
        self.assertTrue(
            da_vista <= colunas,
            f"o contrato pede o que a vista nao da: {sorted(da_vista - colunas)}",
        )
        self.assertNotIn("disponivel", colunas)

        # **O dominio escrito ao lado do `preco_tipo`, que o `split(" ")` acima
        # deixa cair** — e e exactamente onde o vocabulario preterido
        # reentraria. A revisao adversarial mediu: se o §6.3 passasse a escrever
        # o mapeamento que o criterio 1 proibe, o caso ficava **verde**, porque
        # os nomes dos campos nao mudavam. Aqui afirma-se a cadeia do dominio.
        dominio = re.search(r"preco_tipo \(([^)]*)\)", achado.group(1))
        self.assertIsNotNone(dominio, "o §6.3 deixou de escrever o dominio inline")
        assert dominio is not None  # para o verificador de tipos
        valores = {v.strip().strip("'") for v in dominio.group(1).split("|")}
        self.assertEqual(valores, {"fixo", "a_partir_de", "sob_consulta"})

    def test_o_lido_em_e_o_instante_da_leitura_e_e_estavel(self) -> None:
        """O `lido_em` do contrato: a hora a que a oferta **foi lida**.

        Tres asercoes, e a revisao adversarial mostrou que a primeira versao so
        fazia a primeira — corria **uma** instrucao, e isso media «um valor por
        instrucao», que um `statement_timestamp()` tambem satisfaz:

        1. **igual nas linhas da mesma leitura** — duas linhas com instantes
           diferentes diziam que a oferta foi lida duas vezes;
        2. **igual em duas instrucoes da mesma transaccao**, que e o que
           distingue o `now()` (instante da transaccao) de um
           `statement_timestamp()` ou de um `clock_timestamp()`;
        3. **proximo do agora**, com tolerancia curta — a de 300 s da primeira
           versao deixava sobreviver um `now() - interval '2 minutes'`.
        """
        tenant = self.criar_tenant()
        self.criar_oferta(tenant, sku="um")
        self.criar_oferta(tenant, sku="dois")
        # `ComBase.ligar` nunca confirma, pelo que as duas instrucoes abaixo
        # correm na **mesma** transaccao — que e a premissa da asercao 2.
        cursor = self.ligar("admin").cursor()
        sql = "SELECT lido_em FROM platform.v_oferta_viva WHERE tenant_id = %s"

        cursor.execute(sql, (tenant,))
        primeira = {linha[0] for linha in cursor.fetchall()}
        self.assertEqual(len(primeira), 1, "duas linhas da mesma leitura divergem")

        cursor.execute(sql, (tenant,))
        segunda = {linha[0] for linha in cursor.fetchall()}
        self.assertEqual(
            primeira,
            segunda,
            "o lido_em mudou entre duas instrucoes da mesma transaccao: nao e now()",
        )

        agora = datetime.datetime.now(datetime.timezone.utc)
        self.assertLess(abs((primeira.pop() - agora).total_seconds()), 30)


class TestIsolamentoDaVista(ComOfertas):
    """Criterio 4: `security_invoker` e a RLS herdada (X-04, X-05)."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant_a = self.criar_tenant()
        self.tenant_b = self.criar_tenant()
        self.criar_oferta(self.tenant_a, sku=SKU_PARTILHADO, nome="arroz de A")
        self.criar_oferta(self.tenant_b, sku=SKU_PARTILHADO, nome="arroz de B")

    def test_a_vista_tem_security_invoker(self) -> None:
        """A opcao nao e decorativa, e o `verificar_vistas` do *gate* 6 exige-a
        em **todas** as vistas, sem lista de excepcoes.

        Uma vista corre, por omissao, com os privilegios do dono — e o dono esta
        sujeito a RLS so por causa do `FORCE`. Com `security_invoker` corre como
        quem a consulta, que e o que a politica pressupoe.
        """
        opcoes = self.consultar(
            "SELECT COALESCE(reloptions, '{}') FROM pg_class "
            " WHERE oid = 'platform.v_oferta_viva'::regclass"
        )
        normalizadas = [
            str(o).replace(" ", "").lower() for o in opcoes[0][0]  # type: ignore[index]
        ]
        self.assertIn("security_invoker=true", normalizadas)

    def test_x04_o_contexto_de_a_nao_ve_a_oferta_de_b(self) -> None:
        """**Qual** linha, e nao quantas: a forma que importa (ISO-39).

        O `SKU_PARTILHADO` existe nos dois tenants, pelo que uma leitura que
        devolvesse a linha errada tinha a contagem certa.
        """
        cursor = self.cursor_app(self.tenant_a)
        cursor.execute(
            "SELECT nome FROM platform.v_oferta_viva WHERE sku = %s",
            (SKU_PARTILHADO,),
        )
        nomes = [str(linha[0]) for linha in cursor.fetchall()]
        self.assertEqual(nomes, ["arroz de A"])
        self.assertNotIn("arroz de B", nomes)

    def test_x04_sem_contexto_nenhum_da_zero_linhas(self) -> None:
        """A metade «falha fechada»: sessao **sem** `app.tenant_id`."""
        cursor = self.cursor_app(None)
        cursor.execute("SELECT count(*) FROM platform.v_oferta_viva")
        self.assertEqual(int(cursor.fetchone()[0]), 0)

    def test_a_leitura_do_indice_nao_atravessa_tenants(self) -> None:
        """O isolamento **na leitura composta**, que e o que a tool corre.

        O `tenant_id` vem do estado e nunca do texto (secao 6.3). Este caso
        pergunta pelo `product_ref` de A **no contexto de B** e exige zero
        linhas: sem `security_invoker`, a vista corria como o dono e devolvia-a.
        """
        cursor = self.cursor_app(self.tenant_b)
        cursor.execute(_leitura(((SKU_PARTILHADO, 0.9),)), (self.tenant_a,))
        self.assertEqual([tuple(linha) for linha in cursor.fetchall()], [])

    def test_a_leitura_do_indice_no_proprio_tenant_devolve_a_sua_linha(self) -> None:
        """A sonda positiva do caso acima. Sem ela, o zero nao prova nada."""
        cursor = self.cursor_app(self.tenant_b)
        cursor.execute(_leitura(((SKU_PARTILHADO, 0.9),)), (self.tenant_b,))
        nomes = [str(linha[3]) for linha in cursor.fetchall()]
        self.assertEqual(nomes, ["arroz de B"])

    def test_so_o_kamba_app_le_a_vista_e_so_por_cima_do_privilegio(self) -> None:
        """**O unico oraculo que distingue o `security_invoker` por execucao.**

        Os ensaios cruzados de tenant **nao** o distinguem, e a revisao
        adversarial mediu-o: sem a opcao a vista corre como o dono
        `kamba_migrator`, que e `NOBYPASSRLS` e que o `FORCE` da `offer_terms`
        vincula, e o predicado da `tenant_iso` le a **GUC da sessao** — a mesma
        nos dois casos. Zero linhas com a opcao e sem ela.

        O que muda e o **privilegio**: com `security_invoker` a leitura da vista
        exige `SELECT` na tabela a **quem consulta**; sem ela, bastava o do dono.
        Por isso o caso retira o `SELECT` na `offer_terms` ao `kamba_app` e exige
        que a leitura da vista passe a falhar com `42501` — o que **nao**
        aconteceria se a opcao caisse.

        E afirma a outra metade do criterio: os quatro papeis que a `0028` deixou
        de fora da oferta continuam de fora, e o `kamba_batch` tambem — ele e o
        unico com `BYPASSRLS`, logo o unico leitor para quem esta vista nao
        compra isolamento, e a primeira versao desta revisao dava-lhe `SELECT`
        com uma razao que nao se sustentava.

        **A ordem das instrucoes nao e estilo.** O `REVOKE` e DDL e pede um
        trinco que colide com uma transaccao aberta que tenha lido a tabela: sem
        o `rollback()` antes dele, o ensaio **bloqueia** em vez de falhar, que e
        o modo de falha que o proprio arreio do *gate* 8 nomeia. E o `GRANT`
        volta num `finally`, porque a ligacao de semente e `autocommit` e um
        privilegio retirado sobreviveria ao ensaio.
        """
        cursor = self.cursor_app(self.tenant_a)
        cursor.execute("SELECT count(*) FROM platform.v_oferta_viva")
        self.assertEqual(int(cursor.fetchone()[0]), 1, "a sonda positiva nao le")
        # Liberta o trinco de leitura antes do DDL.
        cursor.connection.rollback()

        self.semente.execute("REVOKE SELECT ON platform.offer_terms FROM kamba_app")
        try:
            cursor = self.cursor_app(self.tenant_a)
            self.assertErroSql(
                "42501", cursor, "SELECT count(*) FROM platform.v_oferta_viva"
            )
            cursor.connection.rollback()
        finally:
            self.semente.execute("GRANT SELECT ON platform.offer_terms TO kamba_app")

        # E a vista volta a ler-se, que e o que prova que o `finally` reparou.
        cursor = self.cursor_app(self.tenant_a)
        cursor.execute("SELECT count(*) FROM platform.v_oferta_viva")
        self.assertEqual(int(cursor.fetchone()[0]), 1)

    def test_os_papeis_sem_oferta_continuam_sem_a_vista(self) -> None:
        """A fronteira que a `0028` escreveu, afirmada sobre a vista.

        **Nos dois sentidos**, que e o que distingue uma lista viva de uma
        declaracao morta: o `kamba_app` tem `SELECT` e os outros **nao**. Sem a
        segunda metade, retirar o unico `GRANT` desta revisao era uma mutacao que
        nenhum ensaio matava.

        O `kamba_batch` esta entre os que nao tem, e e deliberado — ver a nota do
        `PAPEL_DA_APP` na revisao `0037`.
        """
        concedidos = {
            str(linha[0])
            for linha in self.consultar(
                "SELECT grantee FROM information_schema.role_table_grants "
                " WHERE table_schema = 'platform' AND table_name = 'v_oferta_viva' "
                "   AND privilege_type = 'SELECT'"
            )
        }
        self.assertIn("kamba_app", concedidos)
        for papel in (
            "kamba_batch",
            "kamba_resolver",
            "kamba_identity",
            "kamba_audit",
            "kamba_agr",
        ):
            with self.subTest(papel=papel):
                self.assertNotIn(papel, concedidos)


class TestPlanoDeExecucao(ComOfertas):
    """Criterio 6: o *join* usa o indice da chave primaria."""

    #: O criterio pede 10 000 SKUs de um tenant. E o numero que torna o
    #: `seq scan` caro o suficiente para o planeador o recusar — com uma tabela
    #: pequena ele escolhe-o com razao, e o ensaio media a cardinalidade e nao o
    #: indice.
    SKUS = 10_000

    def test_o_join_por_product_ref_nao_faz_seq_scan_na_offer_terms(self) -> None:
        """O plano, com volume, e depois do `ANALYZE`.

        Sem `ANALYZE` o planeador trabalha com estatisticas de uma tabela vazia
        e escolhe o `seq scan` por nao saber que ha 10 000 linhas — o ensaio
        falhava por nao ter medido, e nao por defeito do indice.
        """
        tenant = self.criar_tenant()
        self.semente.execute(
            "INSERT INTO platform.offer_terms "
            "(tenant_id, sku, nome, preco_tipo, preco_minor, stock_modo, estado) "
            "SELECT %s, 'sku-' || g, 'produto ' || g, 'fixo', 1000 + g, "
            "       'garantido', 'publicado' "
            "  FROM generate_series(1, %s) AS g",
            (tenant, self.SKUS),
        )
        self.semente.execute("ANALYZE platform.offer_terms")
        # **Como `kamba_app` e nao como administrador**, e a revisao adversarial
        # tem razao em exigi-lo: o plano que o superutilizador recebe nao leva a
        # *qual* da RLS, pelo que os criterios 4 e 6 nunca eram verdadeiros na
        # mesma sessao — media-se o indice num plano que o leitor real nao
        # recebe. Aqui o plano leva por cima o predicado da `tenant_iso`, e a
        # asercao continua a ser a mesma: a condicao da juncao e `text = text`,
        # *leakproof*, pelo que a barreira de seguranca nao trava o indice.
        cursor = self.cursor_app(tenant)
        cursor.execute("EXPLAIN " + _leitura((("sku-7777", 0.9),)), (tenant,))
        plano = "\n".join(str(linha[0]) for linha in cursor.fetchall())
        # **A ordem das duas asercoes nao e indiferente.** O `assertIn` do
        # `offer_terms_pkey` vem a seguir porque e ele que impede o verde vazio:
        # um `assertNotIn` sozinho passava se o plano viesse em branco, se a
        # consulta mudasse de forma ou se o *join* desaparecesse — o que nao
        # contem «Seq Scan» por nao conter nada.
        self.assertNotIn(
            "Seq Scan on offer_terms",
            plano,
            f"o join por (tenant_id, product_ref) nao cai no indice:\n{plano}",
        )
        self.assertIn("offer_terms_pkey", plano, f"plano sem a chave primaria:\n{plano}")


class TestDowngradeDa0037(unittest.TestCase):
    """Criterio 8: «Migracao com `downgrade` testado».

    O ciclo `upgrade -> downgrade -> upgrade` do *gate* 8
    (`tests/test_migracao.TestCiclo`) desce a cadeia inteira e nao nomeia nada:
    uma falha dele diz «a cadeia nao reaplica» e nao **qual** objecto nao
    voltou. O que esta classe acrescenta e a afirmacao sobre **este** objecto, e
    uma propriedade que o ciclo e cego para ela: o `downgrade` nao leva
    `CASCADE`, pelo que uma vista deixada pendurada faria o `DROP TABLE` de uma
    revisao **abaixo** falhar com `2BP01` — e o sintoma aparecia a revisoes de
    distancia da causa.

    **A vista nao e uma tabela, e isso e metade do que se mede aqui.** O
    `pg_tables` nao a lista, pelo que a revisao nao acrescenta nada ao `TABELAS`
    do `db/tests/base.py` e os ensaios de `downgrade` das outras revisoes nao a
    vem. Quem a ve e o `VISTAS`, e e contra o `pg_views` que se pergunta.

    Nao herda de `ComOfertas`: controla ela propria a revisao em que a base
    esta, como o `TestDowngradeDa0028` ao lado. Repoe `head` no fim, corra bem
    ou mal.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()

    def tearDown(self) -> None:
        try:
            if not em_head():
                alembic_ok("upgrade", "head")
        finally:
            self.conexao.close()

    def vista_existe(self) -> int:
        self.cursor.execute(
            "SELECT count(*) FROM pg_views "
            " WHERE schemaname = 'platform' AND viewname = 'v_oferta_viva'"
        )
        return int(self.cursor.fetchone()[0])

    def test_desce_para_a_0036_e_a_vista_cai(self) -> None:
        """E a `offer_terms` **fica**: a vista nao e dona de nada.

        A segunda metade importa tanto como a primeira. Um `downgrade` que
        levasse a tabela com a vista destruia o catalogo de todos os tenants
        para desfazer um contrato de leitura, e o `upgrade` seguinte deixava a
        base «certa em `head`» com os dados apagados por baixo.
        """
        self.assertEqual(self.vista_existe(), 1)

        alembic_ok("downgrade", "0036")
        self.assertEqual(self.vista_existe(), 0, "o downgrade deixou a vista para tras")
        self.cursor.execute(
            "SELECT count(*) FROM pg_tables "
            " WHERE schemaname = 'platform' AND tablename = 'offer_terms'"
        )
        self.assertEqual(
            int(self.cursor.fetchone()[0]), 1, "o downgrade levou a tabela de origem"
        )

        alembic_ok("upgrade", "head")
        self.assertEqual(self.vista_existe(), 1)

    def test_depois_de_descer_e_subir_a_vista_volta_com_security_invoker(self) -> None:
        """**A propriedade que um `DROP`/`CREATE` perde em silencio.**

        Uma vista que voltasse sem `security_invoker` passava a correr com os
        privilegios do dono: o criterio 4 caia e a RLS deixava de valer para
        quem a le, com a base a parecer certa em `head` e o *gate* 6 a ser o
        unico a notar. Aqui afirma-se no ciclo, que e onde se perderia.
        """
        alembic_ok("downgrade", "0036")
        alembic_ok("upgrade", "head")
        self.cursor.execute(
            "SELECT COALESCE(reloptions, '{}') FROM pg_class "
            " WHERE oid = 'platform.v_oferta_viva'::regclass"
        )
        opcoes = [str(o).replace(" ", "").lower() for o in self.cursor.fetchone()[0]]
        self.assertIn("security_invoker=true", opcoes)

    def test_as_nove_colunas_voltam_na_mesma_ordem(self) -> None:
        """O contrato e a **ordem**, e um `CREATE VIEW` reescrito reordena-a.

        Quem consome `SELECT v.*` le por posicao. Esta e a asercao que distingue
        «a vista voltou» de «a vista voltou igual».
        """
        alembic_ok("downgrade", "0036")
        alembic_ok("upgrade", "head")
        self.cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            " WHERE table_schema = 'platform' AND table_name = 'v_oferta_viva' "
            " ORDER BY ordinal_position"
        )
        self.assertEqual(
            tuple(str(linha[0]) for linha in self.cursor.fetchall()), COLUNAS
        )
