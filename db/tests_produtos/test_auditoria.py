"""Criterio 5 do KAM-043: a auditoria e os eventos de preco e de stock.

«Alterar preco ou stock grava `audit_log` (actor, *hash* antes/depois, origem) e
emite `price.changed`/`stock.changed` (e `stock.low` abaixo do limiar,
*proposta*); `product.published`/`product.updated` **nao contem preco nem
stock** (ADR-007).»

## Os nomes dos eventos sao os do catalogo publicado

Dos cinco que o criterio escreve, **um** existe: o `stock.low`. Os outros quatro
nao tem contrato, nao estao no dicionario §3.5 e nao estao no `docs/tecnica/06`
§5. Os que servem este ticket chamam-se `catalog.price_changed`,
`stock.adjusted`, `stock.low` e `catalog.product_changed`, e este ficheiro
exercita-os por esses nomes — a resolucao esta no `eventos.ts` do modulo, na
emenda 1.52 do dicionario e na divida 37.

## O que so aqui se prova

O `evt_emitir` e o `audit_append` sao **funcoes de base de dados**. O que uma
base falsa compara e o texto da chamada; o que esta suite mede e o envelope que
sai e a linha que entra — incluindo o que o `evt_emitir` **recusa**, que e a
unica forma de afirmar que a regra do telefone tem quem a imponha e nao so quem
a escreva.
"""

from __future__ import annotations

import hashlib
import json

from tests_produtos import consultas
from tests_produtos.base import PRECO, SKU_PARTILHADO, ComOfertas

#: O separador do texto canonico do `payload_hash`: US (*unit separator*), o
#: mesmo que a revisao `0006` e o `db/auditoria.py` usam para a cadeia.
SEPARADOR = "\u001f"


def texto_do_hash(accao: str, sku: str, antes: str, depois: str, origem: str) -> str:
    """A reconstrucao independente do que o modulo resume.

    **Independente de proposito**, como o `db/auditoria.py` faz com o `row_hash`:
    se este ficheiro chamasse a funcao do modulo, provava que ela e igual a si
    mesma. Aqui esta a forma, escrita a mao, e e ela que o teste compara.
    """
    return SEPARADOR.join([accao, sku, antes, depois, origem])


class TestAAuditoriaDePrecoEDeStock(ComOfertas):
    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.criar_oferta(self.tenant)
        self.cursor = self.cursor_app(self.tenant)

    def auditar(self, accao: str, texto: str, *, actor_type: str = "owner"):
        consulta = consultas.SQL_AUDITAR
        self.cursor.execute(
            consulta.sql,
            consulta.args(
                self.tenant,
                actor_type,
                "o-dono",
                accao,
                "offer_terms",
                SKU_PARTILHADO,
                None,
                texto,
            ),
        )

    def test_as_duas_accoes_do_ticket_entram_na_cadeia(self) -> None:
        """`price.update` e `stock.adjust` — as duas que o dicionario §3.2 ja
        tinha, e que este modulo passa a ser o primeiro a escrever em producao."""
        self.auditar("price.update", texto_do_hash(
            "price.update", SKU_PARTILHADO, "preco_minor=1", "preco_minor=2",
            "upsert_rascunho",
        ))
        self.auditar("stock.adjust", texto_do_hash(
            "stock.adjust", SKU_PARTILHADO, "stock_modo=garantido",
            "stock_modo=indicativo", "ajuste_de_stock",
        ))
        self.cursor.connection.commit()
        self.assertEqual(
            self.auditoria(self.tenant),
            [
                ("owner", "o-dono", "price.update", "offer_terms", SKU_PARTILHADO),
                ("owner", "o-dono", "stock.adjust", "offer_terms", SKU_PARTILHADO),
            ],
        )

    def test_o_payload_hash_e_o_sha256_do_par_antes_depois_e_da_origem(self) -> None:
        """O criterio pede «*hash* antes/depois, origem», e e isto.

        O que a linha prova e que **alguem com este actor alterou isto neste
        instante, e que o antes e o depois eram estes**: quem tiver os dois
        valores confirma-o. Quem nao os tiver nao os reconstroi do *hash* — e e
        uma limitacao e nao um descuido, porque o `audit_log` nao guarda
        conteudo.
        """
        texto = texto_do_hash(
            "price.update",
            SKU_PARTILHADO,
            "preco_minor=1250000,preco_tipo=fixo",
            "preco_minor=1500000,preco_tipo=fixo",
            "upsert_rascunho",
        )
        self.auditar("price.update", texto)
        self.cursor.connection.commit()
        esperado = hashlib.sha256(texto.encode("utf-8")).digest()
        self.assertEqual(self.hashes_de_auditoria(self.tenant), [esperado])

    def test_uma_accao_fora_das_sete_do_dominio_falha_na_bd(self) -> None:
        """O dominio de `action` esta fechado em **sete** no `CHECK` da `0006`.

        E e por isto que a emenda 1.52 **nao** o repete como dominio de dois: um
        dominio fechado tem um sitio, e declarar um subconjunto noutro punha o
        `canon_lint` vermelho — medido.
        """
        consulta = consultas.SQL_AUDITAR
        self.assertErroSql(
            "23514",
            self.cursor,
            consulta.sql,
            consulta.args(
                self.tenant, "owner", "o-dono", "price.invent", "offer_terms",
                SKU_PARTILHADO, None, "x",
            ),
        )

    def test_um_actor_type_fora_dos_cinco_falha_na_bd(self) -> None:
        """O mapa do dicionario §3.40 traduz os quatro `actor.kind` da porta
        para estes cinco. Um `agente` cru — em portugues — e recusado."""
        consulta = consultas.SQL_AUDITAR
        self.assertErroSql(
            "23514",
            self.cursor,
            consulta.sql,
            consulta.args(
                self.tenant, "agente", "o-agente", "price.update", "offer_terms",
                SKU_PARTILHADO, None, "x",
            ),
        )

    def test_os_quatro_actor_type_do_mapa_sao_aceites(self) -> None:
        """O caminho legitimo dos quatro, e o `contact` fica de fora **de
        proposito**: um cliente nunca altera preco nem stock."""
        for actor_type in ("agent", "owner", "system", "staff"):
            with self.subTest(actor_type=actor_type):
                self.auditar("price.update", f"x{actor_type}", actor_type=actor_type)
        self.cursor.connection.commit()
        self.assertEqual(
            [linha[0] for linha in self.auditoria(self.tenant)],
            ["agent", "owner", "system", "staff"],
        )

    def test_a_cadeia_encadeia_se_e_o_chamador_nao_escolhe_o_prev_hash(self) -> None:
        """O `audit_encadear` escreve `criado_at`, `prev_hash` e `row_hash`.

        Esta e a propriedade do KAM-012 de que este ticket passa a depender, e
        que ninguem exercitava em producao: sem ela, quem tem `INSERT` forja uma
        linha correctamente encadeada com a data que quiser.
        """
        for i in range(3):
            self.auditar("price.update", f"alteracao-{i}")
        self.cursor.connection.commit()
        linhas = self.consultar(
            "SELECT prev_hash, row_hash FROM platform.audit_log "
            " WHERE tenant_id = %s ORDER BY id",
            (self.tenant,),
        )
        self.assertEqual(len(linhas), 3)
        # Cada `prev_hash` e o `row_hash` da linha anterior.
        for anterior, seguinte in zip(linhas, linhas[1:]):
            self.assertEqual(bytes(seguinte[0]), bytes(anterior[1]))
        # E nenhum `row_hash` se repete: tres alteracoes, tres elos.
        self.assertEqual(len({bytes(l[1]) for l in linhas}), 3)


class TestOsEventosDeCatalogoEDeStock(ComOfertas):
    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.criar_oferta(self.tenant)
        self.cursor = self.cursor_app(self.tenant)

    def emitir(self, tipo: str, agregado: str, payload: dict, *, versao: int = 1):
        consulta = consultas.SQL_EMITIR
        self.cursor.execute(
            consulta.sql,
            consulta.args(
                tipo,
                versao,
                self.tenant,
                agregado,
                SKU_PARTILHADO,
                json.dumps(payload),
                "P0",
                ["transacao"],
            ),
        )
        return str(self.cursor.fetchone()[0])

    def test_o_evento_de_produto_nao_leva_preco_nem_stock(self) -> None:
        """A letra do fim do criterio 5, e o ADR-007 onde ele morde.

        O payload do `catalog.product_changed` e `{sku, estado}` e mais nada: o
        contrato v1 tem `additionalProperties: false` e `properties` com duas
        chaves. **Este caso le o envelope que saiu** e afirma a ausencia, em vez
        de confiar no schema.
        """
        self.emitir(
            "catalog.product_changed", "product",
            {"sku": SKU_PARTILHADO, "estado": "publicado"},
        )
        self.cursor.connection.commit()
        envelopes = self.eventos(self.tenant, "catalog.product_changed")
        self.assertEqual(len(envelopes), 1)
        payload = envelopes[0]["payload"]
        self.assertEqual(set(payload), {"sku", "estado"})
        for proibido in ("preco_minor", "preco_tipo", "qty", "stock_modo", "currency"):
            self.assertNotIn(proibido, payload)

    def test_o_evento_de_preco_leva_o_preco_e_isso_e_o_que_o_adr_007_diz(self) -> None:
        """**E a parte que uma leitura apressada do ADR-007 inverte.**

        O ADR-007, a letra: «preco e stock nunca em embeddings nem em prompts».
        Nao diz «nem no corpo dos eventos». O `docs/tecnica/06` diz onde morde —
        «o IDX nao precisa de preco (ADR-007) e nao deve reindexar a cada
        alteracao de preco» — e manda o DAT **construir** o `preco_obs` a partir
        deste evento. Um `catalog.price_changed` sem `preco_minor` deixava o
        consumidor documentado sem nada para observar.
        """
        self.emitir(
            "catalog.price_changed", "product",
            {
                "sku": SKU_PARTILHADO,
                "preco_tipo": "fixo",
                "preco_minor": PRECO,
                "currency": "AOA",
            },
        )
        self.cursor.connection.commit()
        payload = self.eventos(self.tenant, "catalog.price_changed")[0]["payload"]
        self.assertEqual(payload["preco_minor"], PRECO)
        self.assertEqual(payload["preco_tipo"], "fixo")

    def test_o_sob_consulta_sai_sem_preco_minor_e_nao_com_nulo(self) -> None:
        """Um `null` afirmava que ha um preco cujo valor e nulo, em vez de nao
        haver preco. E a mesma distincao que o `offer_terms_preco_ck` faz."""
        self.emitir(
            "catalog.price_changed", "product",
            {"sku": SKU_PARTILHADO, "preco_tipo": "sob_consulta", "currency": "AOA"},
        )
        self.cursor.connection.commit()
        payload = self.eventos(self.tenant, "catalog.price_changed")[0]["payload"]
        self.assertNotIn("preco_minor", payload)

    def test_os_dois_eventos_de_stock_levam_a_quantidade(self) -> None:
        self.emitir(
            "stock.adjusted", "sku",
            {"sku": SKU_PARTILHADO, "qty": 3, "motivo": "ajuste_do_dono"},
        )
        self.emitir("stock.low", "sku", {"sku": SKU_PARTILHADO, "qty": 3})
        self.cursor.connection.commit()
        self.assertEqual(
            self.eventos(self.tenant, "stock.adjusted")[0]["payload"]["qty"], 3
        )
        self.assertEqual(
            self.eventos(self.tenant, "stock.low")[0]["payload"]["qty"], 3
        )

    def test_o_agregado_de_catalogo_e_product_e_o_de_stock_e_sku(self) -> None:
        """Os `const` dos contratos v1, e as sequencias sao linhagens separadas.

        Usar o mesmo `agregado_tipo` nos quatro fazia a sequencia de preco e a de
        stock serem a mesma — e o `evt_agregado_seq` da a sequencia por
        `(tipo, id)`.
        """
        self.emitir(
            "catalog.price_changed", "product",
            {"sku": SKU_PARTILHADO, "preco_tipo": "fixo", "preco_minor": PRECO,
             "currency": "AOA"},
        )
        self.emitir(
            "stock.adjusted", "sku",
            {"sku": SKU_PARTILHADO, "qty": 1, "motivo": "conferencia"},
        )
        self.cursor.connection.commit()
        preco = self.eventos(self.tenant, "catalog.price_changed")[0]
        stock = self.eventos(self.tenant, "stock.adjusted")[0]
        self.assertEqual(preco["agregado"]["tipo"], "product")
        self.assertEqual(stock["agregado"]["tipo"], "sku")
        # Duas linhagens: as duas comecam em 1 para o mesmo `sku`.
        self.assertEqual(preco["agregado"]["seq"], 1)
        self.assertEqual(stock["agregado"]["seq"], 1)

    def test_um_payload_com_padrao_de_telefone_e_recusado_pela_base(self) -> None:
        """A regra tem **quem a imponha**, e nao so quem a escreva.

        O `evt_emitir` levanta `check_violation` sobre um payload cujo texto
        casa com um padrao de telefone. E o unico caso deste ficheiro que nao e
        sobre este ticket: esta aqui porque e a barreira que torna «sem PII nos
        eventos» uma propriedade e nao uma intencao, e porque este ticket emite
        quatro tipos novos atraves dela.
        """
        consulta = consultas.SQL_EMITIR
        self.assertErroSql(
            "23514",
            self.cursor,
            consulta.sql,
            consulta.args(
                "catalog.product_changed", 1, self.tenant, "product",
                SKU_PARTILHADO,
                json.dumps({"sku": "+244923456789", "estado": "publicado"}),
                "P0", ["transacao"],
            ),
        )

    def test_a_emissao_corre_na_transaccao_de_quem_escreve(self) -> None:
        """O outbox e um outbox: a escrita e o evento entram ou nao entram juntos.

        Com um `rollback`, **nem a oferta nem o evento** ficam — e e isso que
        dispensa reconciliacao entre a tabela e a fila.
        """
        self.cursor.execute(
            "INSERT INTO platform.offer_terms "
            "(tenant_id, sku, nome, preco_tipo, preco_minor) "
            "VALUES (%s, 'novo', 'Produto novo', 'fixo', 100)",
            (self.tenant,),
        )
        self.emitir(
            "catalog.product_changed", "product",
            {"sku": "novo", "estado": "rascunho"},
        )
        self.cursor.connection.rollback()
        self.assertEqual(self.tipos_emitidos(self.tenant), [])
        self.assertEqual(
            [sku for sku, *_ in self.ofertas(self.tenant)], [SKU_PARTILHADO]
        )
