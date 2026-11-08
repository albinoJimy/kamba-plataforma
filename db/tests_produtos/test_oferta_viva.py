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
from pathlib import Path

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
        casos = (
            ("pausado", {"estado": "pausado"}),
            ("arquivado", {"estado": "arquivado"}),
            ("restrito", {"categoria_restrita": "farmacia"}),
            ("apagado", {"deleted_at": daqui_a(horas=-1)}),
        )
        for nome, mudanca in casos:
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
        casos = (
            ("pausado", {"estado": "pausado"}),
            ("arquivado", {"estado": "arquivado"}),
            ("restrito", {"categoria_restrita": "farmacia"}),
            ("apagado", {"deleted_at": daqui_a(horas=-1)}),
        )
        for nome, mudanca in casos:
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

    def test_o_lido_em_e_o_instante_da_leitura_e_e_estavel(self) -> None:
        """O `lido_em` do contrato: a hora a que a oferta **foi lida**.

        Estavel dentro da transaccao — duas linhas da mesma leitura com
        instantes diferentes diziam que a oferta foi lida duas vezes —, e
        proximo do agora, que e o que distingue um `now()` de uma coluna
        guardada.
        """
        tenant = self.criar_tenant()
        self.criar_oferta(tenant, sku="um")
        self.criar_oferta(tenant, sku="dois")
        cursor = self.ligar("admin").cursor()
        cursor.execute(
            "SELECT lido_em FROM platform.v_oferta_viva WHERE tenant_id = %s",
            (tenant,),
        )
        instantes = {linha[0] for linha in cursor.fetchall()}
        self.assertEqual(len(instantes), 1)
        agora = datetime.datetime.now(datetime.timezone.utc)
        self.assertLess(abs((instantes.pop() - agora).total_seconds()), 300)


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
        plano = "\n".join(
            str(linha[0])
            for linha in self.consultar(
                "EXPLAIN " + _leitura((("sku-7777", 0.9),)), (tenant,)
            )
        )
        self.assertNotIn(
            "Seq Scan on offer_terms",
            plano,
            f"o join por (tenant_id, product_ref) nao cai no indice:\n{plano}",
        )
        self.assertIn("offer_terms_pkey", plano, f"plano sem a chave primaria:\n{plano}")
