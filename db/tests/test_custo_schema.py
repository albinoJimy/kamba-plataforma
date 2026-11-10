"""A `platform.v_tenant_cost_daily` contra a base (KAM-081).

O SQL da vista **nao esta copiado aqui**: vem de `db/custo.py`, o mesmo modulo
que a revisao chama. O que este ficheiro prova, contra um PostgreSQL:

1. **As colunas sao exactamente as de `custo.COLUNAS`, e nenhuma aponta para
   uma pessoa** (criterio 7). E o ensaio que fica vermelho se a vista passar a
   expor o `contact_id` — por igualdade **e** pela lista de proibidos, pelo que
   uma coluna nova com outro nome tambem o pinta.
2. **Os totais de uma *fixture* com valores conhecidos**, rubrica a rubrica: o
   LLM sem as recusas de destino e com o `sem_preco`, a Meta so nas entregues e
   cobraveis, a categoria desconhecida em `meta_outra` com custo nulo, e a
   conversao para Kz igual a do Python.
3. **O cambio e parametro** (criterio 1): `app.fx_aoa_per_usd` muda o Kz e a
   coluna que o diz; um valor ilegivel levanta em vez de cair na omissao.
4. **O dia e o do fuso do tenant.**
5. **So o `kamba_batch` le**: o `kamba_app` e o `kamba_audit` recebem `42501`.
6. **O `h6-export` corre contra a base** e nao devolve o contacto.

Escreve em `dat.llm_call_log`, que e *append-only*: tudo corre numa transaccao
que nunca confirma, como `admin`, e o `SET LOCAL ROLE` mede os papeis dentro
dela.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
_NUCLEO = str(_RAIZ / "libs" / "py-core" / "src")
if _NUCLEO not in sys.path:
    sys.path.insert(0, _NUCLEO)

import custo  # noqa: E402
import h6_export as h6  # noqa: E402
from tests import factories  # noqa: E402
from tests.base import ComBase  # noqa: E402

UTC = dt.timezone.utc
DIA = dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class TestVistaDeCusto(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)
        self.canal = factories.canal(self.cursor, self.tenant)
        self.contacto = factories.contacto(self.cursor, self.tenant)
        self.conversa = str(uuid.uuid4())
        self.cursor.execute(
            "INSERT INTO platform.conversations (id, tenant_id, contact_id, channel_id) "
            "VALUES (%s, %s, %s, %s)",
            (self.conversa, self.tenant, self.contacto, self.canal),
        )

    # ------------------------------------------------------------ sementes

    def _chamada(self, custo_usd: str | None, quando=DIA, resultado="ok", tokens=10) -> None:
        negado = resultado == "destino_negado"
        self.cursor.execute(
            "INSERT INTO dat.llm_call_log "
            "(ts, tenant_id, trace_id, vertical, no_grafo, papel, graph_version, "
            " modelo, fornecedor, tokens_in, tokens_out, tokens_cache, "
            " custo_usd, latencia_ms, resultado) "
            "VALUES (%s, %s, %s, 'vendedor', 'no_de_teste', 'chat', '1.0.0', "
            " 'modelo-de-teste', 'fornecedor_de_teste', %s, %s, %s, %s, 1, %s)",
            (
                quando,
                self.tenant,
                str(uuid.uuid4()),
                None if negado else tokens,
                None if negado else tokens,
                None if negado else 0,
                None if negado else custo_usd,
                resultado,
            ),
        )

    def _mensagem(self, pricing: dict | None, entregue: bool = True, quando=DIA) -> None:
        self.cursor.execute(
            "INSERT INTO platform.outbound_messages "
            "(id, tenant_id, channel_id, contact_id, conversation_id, idempotency_key, "
            " wamid, kind, state, pricing, created_at, delivered_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'service', %s, %s::jsonb, %s, %s)",
            (
                str(uuid.uuid4()),
                self.tenant,
                self.canal,
                self.contacto,
                self.conversa,
                f"chave-{uuid.uuid4()}",
                f"wamid.ENSAIO{uuid.uuid4().hex[:12]}",
                "delivered" if entregue else "sent",
                None if pricing is None else json.dumps(pricing),
                quando,
                quando if entregue else None,
            ),
        )

    def _linhas(self) -> dict[str, tuple]:
        self.cursor.execute(
            "SELECT rubrica, dia, unidades, sem_preco, custo_usd, custo_aoa_minor, "
            "       fx_aoa_per_usd "
            "  FROM platform.v_tenant_cost_daily WHERE tenant_id = %s",
            (self.tenant,),
        )
        return {linha[0]: tuple(linha[1:]) for linha in self.cursor.fetchall()}

    # -------------------------------------------------------------- ensaios

    #: As colunas da vista, **escritas aqui** e nao importadas do `custo.COLUNAS`:
    #: um oraculo importado do alvo muda com ele. A revisao adversarial (A6)
    #: projectou `o.contact_id AS contacto`, acrescentou `contacto` ao
    #: `COLUNAS`, e o ensaio que comparava com o modulo ficou verde.
    COLUNAS_ESPERADAS = (
        ("tenant_id", "uuid"),
        ("dia", "date"),
        ("rubrica", "text"),
        ("unidades", "bigint"),
        ("sem_preco", "bigint"),
        ("custo_usd", "numeric"),
        ("custo_aoa_minor", "bigint"),
        ("fx_aoa_per_usd", "numeric"),
    )

    def test_as_colunas_sao_estas_e_nenhuma_aponta_para_pessoas(self) -> None:
        """Criterio 7. Fica vermelho se a vista expuser o `contact_id`, com que nome for.

        Tres cercas: a lista literal acima, por igualdade; o modulo, que tem de
        dizer o mesmo; e **so uma coluna `uuid`**, a do tenant — um contacto, uma
        conversa ou um canal com outro nome continuam a ser `uuid`.
        """
        self.cursor.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            " WHERE table_schema = 'platform' AND table_name = 'v_tenant_cost_daily' "
            " ORDER BY ordinal_position"
        )
        colunas = tuple(tuple(linha) for linha in self.cursor.fetchall())
        self.assertEqual(colunas, self.COLUNAS_ESPERADAS)
        self.assertEqual(tuple(nome for nome, _ in colunas), custo.COLUNAS)
        self.assertEqual([n for n, tipo in colunas if tipo == "uuid"], ["tenant_id"])
        self.assertEqual({n for n, _ in colunas} & h6.IDENTIFICADORES_PROIBIDOS, set())

    def test_um_billable_que_nao_e_booleano_nao_conta_e_nao_derruba_a_vista(self) -> None:
        """Achado A10: `"yes"` contava, e `"talvez"` levantava para todos os tenants."""
        self._mensagem({"billable": "yes", "category": "service"})
        self._mensagem({"billable": "talvez", "category": "service"})
        self._mensagem({"category": "service"})
        self.assertEqual(self._linhas(), {})

    def test_um_cambio_nao_positivo_levanta(self) -> None:
        """Achado A11: com `-913` a vista dava custos negativos."""
        self._mensagem({"billable": True, "category": "service"})
        for valor in ("-913", "0"):
            with self.subTest(valor=valor):
                self.cursor.execute("SAVEPOINT cambio")
                self.cursor.execute(f"SET LOCAL app.fx_aoa_per_usd = '{valor}'")
                self.assertErroSql(
                    "22P02", self.cursor, "SELECT * FROM platform.v_tenant_cost_daily"
                )
                self.cursor.execute("ROLLBACK TO SAVEPOINT cambio")

    def test_leva_security_invoker(self) -> None:
        self.cursor.execute(
            "SELECT c.reloptions FROM pg_class c "
            "  JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relname = 'v_tenant_cost_daily'"
        )
        self.assertIn("security_invoker=true", self.cursor.fetchone()[0])

    def test_os_totais_da_fixture(self) -> None:
        """Valores conhecidos, rubrica a rubrica, ao cambio por omissao (913)."""
        self._chamada("0.000450")
        self._chamada("0.001000")
        self._chamada(None)  # tokens sem preco: conta em sem_preco
        self._chamada(None, resultado="destino_negado")  # nao aconteceu: fora
        for _ in range(3):
            self._mensagem({"billable": True, "category": "service", "type": "regular"})
        self._mensagem({"billable": True, "category": "utility", "type": "regular"})
        self._mensagem({"billable": True, "category": "xpto"})
        self._mensagem({"billable": False, "category": "service", "type": "free_customer_service"})
        self._mensagem({"billable": True, "category": "marketing"}, entregue=False)
        self._mensagem(None)

        dia = dt.date(2026, 6, 1)
        fx = Decimal(913)
        self.assertEqual(
            self._linhas(),
            {
                # 0,00145 x 913 x 100 = 132,385 -> 132
                "llm": (dia, 3, 1, Decimal("0.001450"), 132, fx),
                # 0,012 x 913 x 100 = 1.095,6 -> 1.096
                "meta_service": (dia, 3, 0, Decimal("0.012"), 1096, fx),
                # 0,004 x 913 x 100 = 365,2 -> 365
                "meta_utility": (dia, 1, 0, Decimal("0.004"), 365, fx),
                "meta_outra": (dia, 1, 1, None, None, fx),
            },
        )

    def test_a_conversao_e_a_do_python(self) -> None:
        self._chamada("0.000450")
        self._mensagem({"billable": True, "category": "marketing"})
        for _rubrica, (_dia, _u, _s, usd, aoa, fx) in self._linhas().items():
            self.assertEqual(aoa, custo.para_aoa_minor(usd, fx))

    def test_o_cambio_e_parametro_de_sessao(self) -> None:
        self._mensagem({"billable": True, "category": "service"})
        self.cursor.execute("SET LOCAL app.fx_aoa_per_usd = '1232'")
        _dia, _u, _s, usd, aoa, fx = self._linhas()["meta_service"]
        self.assertEqual(fx, Decimal(1232))
        self.assertEqual(aoa, 493)  # 0,004 x 1.232 x 100 = 492,8
        self.cursor.execute("SET LOCAL app.fx_aoa_per_usd = ''")
        self.assertEqual(self._linhas()["meta_service"][5], custo.CAMBIO_POR_OMISSAO)

    def test_um_cambio_ilegivel_levanta(self) -> None:
        self._mensagem({"billable": True, "category": "service"})
        self.cursor.execute("SET LOCAL app.fx_aoa_per_usd = 'novecentos'")
        self.assertErroSql(
            "22P02", self.cursor, "SELECT * FROM platform.v_tenant_cost_daily"
        )

    def test_o_dia_e_o_do_fuso_do_tenant(self) -> None:
        """23:30 UTC em Luanda (UTC+1) ja e o dia seguinte."""
        self._chamada("0.000100", quando=dt.datetime(2026, 6, 1, 23, 30, tzinfo=UTC))
        self.assertEqual(self._linhas()["llm"][0], dt.date(2026, 6, 2))

    def test_so_o_lote_le(self) -> None:
        self._mensagem({"billable": True, "category": "service"})
        self.cursor.execute("SAVEPOINT papel")
        self.cursor.execute("SET LOCAL ROLE kamba_batch")
        self.cursor.execute(
            "SELECT count(*) FROM platform.v_tenant_cost_daily WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 1)
        self.cursor.execute("ROLLBACK TO SAVEPOINT papel")
        for papel in ("kamba_app", "kamba_audit"):
            with self.subTest(papel=papel):
                self.cursor.execute("SAVEPOINT papel")
                self.cursor.execute(f"SET LOCAL ROLE {papel}")
                self.assertErroSql(
                    "42501", self.cursor, "SELECT * FROM platform.v_tenant_cost_daily"
                )
                self.cursor.execute("ROLLBACK TO SAVEPOINT papel")

    def test_o_sql_dos_paineis_corre_como_o_lote(self) -> None:
        """Cada `rawSql` dos dois paineis corre contra a base, como `kamba_batch`.

        Sem isto o SQL dos paineis era proposta: o Grafana nao corre (KAM-080), e
        um erro de sintaxe so aparecia no dia do deploy. As variaveis e a macro de
        tempo trocam-se pelos valores de omissao do proprio painel.
        """
        self._chamada("0.000450")
        self._mensagem({"billable": True, "category": "service"})
        trocas = {
            "$__timeFilter(dia)": "dia BETWEEN '2026-01-01' AND '2027-12-31'",
            "$mensalidade_kz": "30000",
            "$fixo_usd": "470",
            "$fx": "913",
        }
        consultas = 0
        for nome in ("custo-por-tenant", "unit-economics"):
            painel = json.loads(
                (_RAIZ / "ops" / "paineis" / f"{nome}.json").read_text(encoding="utf-8")
            )
            for bloco in painel["panels"]:
                for alvo in bloco.get("targets", []):
                    sql = alvo["rawSql"]
                    for de, para in trocas.items():
                        sql = sql.replace(de, para)
                    self.assertNotIn("$", sql, f"variavel por trocar em {nome}")
                    with self.subTest(painel=nome, titulo=bloco["title"]):
                        self.cursor.execute("SAVEPOINT painel")
                        try:
                            self.cursor.execute("SET LOCAL ROLE kamba_batch")
                            self.cursor.execute(sql)
                            self.assertIsNotNone(self.cursor.fetchall())
                            consultas += 1
                        finally:
                            self.cursor.execute("ROLLBACK TO SAVEPOINT painel")
        self.assertEqual(consultas, 6)

    def _painel(self, nome: str, titulo: str) -> str:
        painel = json.loads(
            (_RAIZ / "ops" / "paineis" / f"{nome}.json").read_text(encoding="utf-8")
        )
        bloco = next(b for b in painel["panels"] if b["title"] == titulo)
        return bloco["targets"][0]["rawSql"]

    def test_o_painel_de_unit_economics_da_os_numeros_do_comando(self) -> None:
        """Achado A1: o painel e o `economia()` sobre os mesmos dados dao o mesmo.

        O Grafana troca as variaveis por texto, e `30000 / 913` em PostgreSQL e
        divisao **inteira** (32, e nao 32,86). O ensaio anterior so via a consulta
        correr; este compara os numeros. Um mes de 2031, para que nenhum dado de
        outro ensaio caia no intervalo.
        """
        quando = dt.datetime(2031, 1, 15, 12, 0, tzinfo=UTC)
        self._chamada("5.500000", quando=quando)
        for _ in range(3):
            self._mensagem({"billable": True, "category": "service"}, quando=quando)
        intervalo = "dia BETWEEN '2031-01-01' AND '2031-01-31'"
        sql = self._painel("unit-economics", "Custo por PME, margem e ponto de equilibrio")
        for de, para in (("$__timeFilter(dia)", intervalo), ("$mensalidade_kz", "30000"),
                         ("$fixo_usd", "470"), ("$fx", "913")):
            sql = sql.replace(de, para)
        self.cursor.execute(sql)
        nomes = [d[0] for d in self.cursor.description]
        painel = dict(zip(nomes, self.cursor.fetchone()))

        self.cursor.execute(h6.SQL_MES, (dt.date(2031, 1, 1), dt.date(2031, 2, 1)))
        por_tenant: dict[str, dict[str, Decimal]] = {}
        for tenant_id, rubrica, valor in self.cursor.fetchall():
            por_tenant.setdefault(tenant_id, {})[rubrica] = Decimal(valor)
        args = (por_tenant, Decimal(470), Decimal(30000), Decimal(913))
        pme = h6.economia(*args, "pme")
        kamba = h6.economia(*args, "kamba")

        q = h6.ESCALA_USD
        self.assertEqual(painel["pmes"], pme["pmes"])
        self.assertEqual(Decimal(painel["mensalidade_usd"]).quantize(q), Decimal(pme["mensalidade_usd"]))
        self.assertEqual(Decimal(painel["custo_fixo_por_pme_usd"]).quantize(q),
                         Decimal(pme["custo_fixo_por_pme_usd"]))
        self.assertEqual(Decimal(painel["custo_para_kamba_por_pme_usd_meta_paga_pela_pme"]).quantize(q),
                         Decimal(pme["custo_para_kamba_por_pme_usd"]))
        self.assertEqual(Decimal(painel["custo_para_kamba_por_pme_usd_meta_paga_pela_kamba"]).quantize(q),
                         Decimal(kamba["custo_para_kamba_por_pme_usd"]))
        self.assertEqual(Decimal(painel["custo_total_cliente_usd_meta_paga_pela_pme"]).quantize(q),
                         Decimal(pme["custo_total_cliente_por_pme_usd"]))
        self.assertEqual(Decimal(painel["custo_total_cliente_usd_meta_paga_pela_kamba"]).quantize(q),
                         Decimal(kamba["custo_total_cliente_por_pme_usd"]))
        self.assertEqual(Decimal(painel["margem_meta_paga_pela_pme"]).quantize(Decimal("0.0001")),
                         Decimal(pme["margem_por_mensalidade"]))
        self.assertEqual(painel["equilibrio_pmes_meta_paga_pela_pme"],
                         pme["ponto_de_equilibrio_pmes"])
        self.assertEqual(painel["equilibrio_pmes_meta_paga_pela_kamba"],
                         kamba["ponto_de_equilibrio_pmes"])

    def test_a_reconciliacao_meta_por_numero_contra_a_base(self) -> None:
        """Achado A4: o medido sai do `pricing` gravado, o estimado da contagem.

        1.003 mensagens de servico entregues num mes, as 1.000 primeiras com
        `billable` falso (o *free tier*), e 2 de utility: a Meta cobrou 5 x 0,004,
        e a tarifa diz o mesmo. O `channel_id` nao sai: sai o ordinal.
        """
        self.cursor.execute(
            "INSERT INTO platform.outbound_messages "
            "(id, tenant_id, channel_id, contact_id, conversation_id, idempotency_key, "
            " wamid, kind, state, pricing, created_at, delivered_at) "
            "SELECT gen_random_uuid(), %s, %s, %s, %s, 'chave-' || g || '-' || gen_random_uuid(), "
            "       'wamid.ENSAIO' || replace(gen_random_uuid()::text, '-', ''), 'service', "
            "       'delivered', jsonb_build_object('billable', g > 1000, 'category', 'service'), "
            "       %s, %s "
            "  FROM generate_series(1, 1003) AS g",
            (self.tenant, self.canal, self.contacto, self.conversa,
             dt.datetime(2031, 2, 10, tzinfo=UTC), dt.datetime(2031, 2, 10, tzinfo=UTC)),
        )
        for _ in range(2):
            self._mensagem({"billable": True, "category": "utility"},
                           quando=dt.datetime(2031, 2, 11, tzinfo=UTC))
        dados, _codigo = h6._correr(
            argparse.Namespace(comando="reconciliar-meta", mes="2031-02"), self.cursor
        )
        meus = [r for r in dados["numeros"] if r["tenant_id"] == self.tenant]
        self.assertEqual(
            meus,
            [{"tenant_id": self.tenant, "numero": 1, "medido_usd_micro": 20_000,
              "pela_tarifa_usd_micro": 20_000, "dentro_da_tolerancia": True}],
        )
        self.assertNotIn(self.canal, json.dumps(dados))
        # E a vista diz o mesmo que o medido: 5 x 0,004.
        self.cursor.execute(
            "SELECT sum(custo_usd) FROM platform.v_tenant_cost_daily "
            " WHERE tenant_id = %s AND rubrica LIKE 'meta_%%'", (self.tenant,)
        )
        self.assertEqual(self.cursor.fetchone()[0], Decimal("0.020"))

    def test_o_h6_export_corre_contra_a_base_sem_devolver_o_contacto(self) -> None:
        # Tres dias atras, ao meio-dia: fechada ha mais de 24 h, e a mais de 24 h
        # do inicio da janela de dez dias — as duas exclusoes do `ultimas`.
        quando = (dt.datetime.now(UTC) - dt.timedelta(days=3)).replace(
            hour=11, minute=0, second=0, microsecond=0
        )
        self._mensagem({"billable": True, "category": "service"}, quando=quando)
        self._mensagem({"billable": True, "category": "utility"},
                       quando=quando + dt.timedelta(minutes=5))
        self._chamada("0.002000", quando=quando)
        # E uma conversa por fechar, de outro contacto: fica de fora da amostra.
        outro = factories.contacto(self.cursor, self.tenant)
        self.cursor.execute(
            "INSERT INTO platform.outbound_messages "
            "(id, tenant_id, channel_id, contact_id, conversation_id, idempotency_key, kind, state) "
            "SELECT gen_random_uuid(), %s, %s, %s, c.id, 'chave-aberta-' || gen_random_uuid(), "
            "       'service', 'queued' "
            "  FROM (SELECT %s::uuid AS id) c",
            (self.tenant, self.canal, outro, self.conversa),
        )
        argumentos = argparse.Namespace(
            comando="exportar", n=100000, janela_dias=10, modo=None, cambio=None,
            mensalidade_kz=Decimal(30000),
        )
        dados, codigo = h6._correr(argumentos, self.cursor)
        self.assertEqual(codigo, h6.SAIDA_OK)
        self.assertGreaterEqual(dados["excluidas"]["por_fechar"], 1)
        minhas = [c for c in dados["conversas"] if c["tenant_id"] == self.tenant]
        self.assertEqual(len(minhas), 1)
        self.assertEqual(minhas[0]["mensagens"], 2)
        self.assertEqual(Decimal(minhas[0]["custo_meta_usd"]), Decimal("0.008"))
        # Se este tenant tem o dia so para si, o rateio devolve o custo inteiro.
        self.assertEqual(Decimal(minhas[0]["custo_llm_usd"]), Decimal("0.002"))
        texto = json.dumps(dados)
        self.assertNotIn(self.contacto, texto)
        self.assertNotIn(self.conversa, texto)
