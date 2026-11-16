"""O custo por modulo de entrada contra a base (KAM-124).

O que so uma base prova, e por isso este ficheiro existe:

1. **O ledger e so de acrescentar e idempotente** (criterio 4): cinco reenvios
   do mesmo custo dao **uma** linha; outro custo com a mesma chave levanta; nem
   o administrador o reescreve, apaga ou trunca; e so o `kamba_batch` escreve.
2. **As vistas** (criterio 6): as colunas sao exactamente as da lista fechada,
   escrita **aqui** e nao importada do alvo; nenhuma aponta para uma pessoa; o
   mes e o de Africa/Luanda; o cambio e o parametro da sessao (913, e +7,4%);
   sem preco, o racio e nulo.
3. **O isolamento** (testes requeridos): o ledger e a vista do mes de A sao
   invisiveis a B; o `kamba_app` nao le a `v_h12`.
4. **A consolidacao** (criterio 5) das tres fontes, idempotente, e o que ela
   deixa de fora: o trabalho de imagem vivo, a recusa de destino, a vertical
   que nao e modulo e o *template* que o mapa nao conhece.
5. **O `h12-export`** sobre a base: `carregar-precos`, `exportar` (sem
   `tenant_id` nem nome), `alertas` e `reconciliar`.
6. **A guarda de orcamento da imagem e o `get_usage`** (criterio 7), pelo SQL
   da biblioteca e com o papel da aplicacao.
7. **O `downgrade`** para a revisao de baixo, lida do ficheiro, sem exigir a
   cabeca depois de descer.

Tudo o que escreve corre numa transaccao do administrador que **nunca
confirma**, e os papeis medem-se com `SET LOCAL ROLE` dentro dela, como no
`test_custo_schema.py`. A revisao encontra-se pelo *glob*
`*_custo_dos_modulos.py`: o numero e provisorio.
"""

from __future__ import annotations

import argparse
import ast
import csv
import datetime as dt
import io
import json
import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

import bootstrap
import ligacao

_RAIZ = Path(__file__).resolve().parents[2]
_NUCLEO = str(_RAIZ / "libs" / "py-core" / "src")
if _NUCLEO not in sys.path:
    sys.path.insert(0, _NUCLEO)

import h12_export as h12  # noqa: E402
import modulos_custo  # noqa: E402
from tests import factories  # noqa: E402
from tests.base import (  # noqa: E402
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    ComBase,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

UTC = dt.timezone.utc
LEDGER = "platform.module_cost_ledger"
PRECOS = "platform.module_test_prices"
REVISAO = next((_RAIZ / "db" / "migrations" / "versions").glob("*_custo_dos_modulos.py"))

#: As colunas das vistas, **por extenso** e nao importadas de `modulos_custo`:
#: um oraculo importado do alvo muda com ele.
COLUNAS_DO_MES = (
    "tenant_id", "mes", "modulo", "rubrica", "unidades", "custo_usd",
    "custo_aoa_minor", "fx_aoa_per_usd",
)
COLUNAS_DA_H12 = (
    "tenant_id", "mes", "modulo", "custo_usd", "custo_aoa_minor", "fx_aoa_per_usd",
    "preco_teste_minor", "racio", "margem_minor",
)
#: O que nenhuma vista pode ter (criterio 6).
PROIBIDAS = ("contact_id", "conversation_id", "telefone", "phone", "wamid", "texto", "body", "nome")

#: Um mes longe de tudo o que os outros ensaios escrevem.
MES = dt.date(2032, 3, 1)
DENTRO = dt.datetime(2032, 3, 10, 12, 0, tzinfo=UTC)

CHAVE = "chave-de-ensaio"


def _literal(nome: str) -> str:
    arvore = ast.parse(REVISAO.read_text(encoding="utf-8"))
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(getattr(t, "id", None) == nome for t in no.targets):
            return ast.literal_eval(no.value)
    raise AssertionError(f"{nome} nao encontrado em {REVISAO.name}")


class BdDoCursor:
    """O `ClienteSql` do `kamba_core` sobre um cursor do pg8000."""

    def __init__(self, cursor) -> None:  # type: ignore[no-untyped-def]
        self.cursor = cursor

    def executar(self, sql: str, parametros=()):  # type: ignore[no-untyped-def]
        from kamba_core.ten.entitlements import Resultado

        self.cursor.execute(sql, tuple(parametros))
        if self.cursor.description is None:
            return Resultado(linhas=())
        nomes = [d[0] for d in self.cursor.description]
        return Resultado(linhas=[dict(zip(nomes, linha)) for linha in self.cursor.fetchall()])


class _ComTransaccao(ComBase):
    """Uma transaccao de administrador que nunca confirma, com um tenant."""

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)
        factories.contexto(self.cursor, None)

    def como(self, papel: str, tenant: str | None = None) -> None:
        self.cursor.execute("RESET ROLE")
        if papel != "admin":
            self.cursor.execute(f"SET LOCAL ROLE {papel}")
        factories.contexto(self.cursor, tenant)

    def gravar(self, tenant: str, custo: str, *, chave: str | None = None, modulo: str = "foto",
               rubrica: str = "imagem", ref: str | None = "ref-1", quando=DENTRO, fx: str = "913"):
        self.como("kamba_batch")
        self.cursor.execute(
            "SELECT gravado, id FROM platform.module_cost_gravar(%s, %s, %s, %s, %s, %s, %s, %s)",
            (tenant, modulo, rubrica, Decimal(custo), ref, chave or f"k-{uuid.uuid4()}", quando, Decimal(fx)),
        )
        resultado = tuple(self.cursor.fetchone())
        self.como("admin")
        return resultado

    def erro(self, esperado: str, sql: str, parametros: tuple = (), texto: str | None = None) -> None:
        import pg8000.dbapi

        self.cursor.execute("SAVEPOINT caso")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                self.cursor.execute(sql, parametros)
        finally:
            self.cursor.execute("ROLLBACK TO SAVEPOINT caso")
        from tests.base import sqlstate

        self.assertEqual(sqlstate(capturado.exception), esperado, str(capturado.exception))
        if texto is not None:
            self.assertIn(texto, str(capturado.exception))

    def linhas(self, tenant: str) -> list[tuple]:
        self.cursor.execute(
            f"SELECT modulo, rubrica, custo_usd, custo_minor, fx_aoa_per_usd, ref FROM {LEDGER} "
            "WHERE tenant_id = %s ORDER BY id",
            (tenant,),
        )
        return [tuple(l) for l in self.cursor.fetchall()]


class TestLedger(_ComTransaccao):
    def test_a_rls_esta_ligada_e_forcada(self) -> None:
        self.cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass", (LEDGER,)
        )
        self.assertEqual(tuple(self.cursor.fetchone()), (True, True))

    def test_cinco_reenvios_do_mesmo_custo_dao_uma_linha(self) -> None:
        """Criterio 4: «reenviar o mesmo custo 5x -> 1 linha»."""
        resultados = [self.gravar(self.tenant, "0.018", chave=CHAVE) for _ in range(5)]
        self.assertEqual([g for g, _ in resultados], [True, False, False, False, False])
        self.assertEqual(len({i for _, i in resultados}), 1)
        self.assertEqual(self.linhas(self.tenant),
                         [("foto", "imagem", Decimal("0.018000"), 1643, Decimal("913"), "ref-1")])

    def test_outro_custo_com_a_mesma_chave_levanta(self) -> None:
        self.gravar(self.tenant, "0.018", chave=CHAVE)
        self.como("kamba_batch")
        for custo, modulo, rubrica, ref in (
            ("0.020", "foto", "imagem", "ref-1"),
            ("0.018", "social", "imagem", "ref-1"),
            ("0.018", "foto", "llm", "ref-1"),
            ("0.018", "foto", "imagem", "ref-2"),
        ):
            with self.subTest(custo=custo, modulo=modulo, rubrica=rubrica, ref=ref):
                self.erro(
                    VIOLACAO_DE_CHECK,
                    "SELECT * FROM platform.module_cost_gravar(%s, %s, %s, %s, %s, %s, %s, 913)",
                    (self.tenant, modulo, rubrica, Decimal(custo), ref, CHAVE, DENTRO),
                    "ja registou outro custo",
                )

    def test_a_funcao_recusa_custo_e_cambio_impossiveis(self) -> None:
        self.como("kamba_batch")
        for custo, fx, texto in (("-0.01", "913", "negativo"), ("0.01", "0", "cambio"), ("0.01", "-1", "cambio")):
            with self.subTest(custo=custo, fx=fx):
                self.erro(
                    VIOLACAO_DE_CHECK,
                    "SELECT * FROM platform.module_cost_gravar(%s, 'foto', 'imagem', %s, 'r', %s, %s, %s)",
                    (self.tenant, Decimal(custo), f"k-{uuid.uuid4()}", DENTRO, Decimal(fx)),
                    texto,
                )

    def test_o_custo_em_kz_e_ao_cambio_do_registo(self) -> None:
        self.gravar(self.tenant, "1.000000", fx="981")
        self.assertEqual(self.linhas(self.tenant)[0][3:5], (98100, Decimal("981")))

    def test_os_dominios_do_modulo_e_da_rubrica(self) -> None:
        self.como("kamba_batch")
        for modulo, rubrica in (("vendedor", "llm"), ("foto", "stt"), ("Foto", "imagem")):
            with self.subTest(modulo=modulo, rubrica=rubrica):
                self.erro(
                    VIOLACAO_DE_CHECK,
                    "SELECT * FROM platform.module_cost_gravar(%s, %s, %s, 0.01, 'r', %s, %s, 913)",
                    (self.tenant, modulo, rubrica, f"k-{uuid.uuid4()}", DENTRO),
                )

    def test_nem_o_administrador_reescreve_apaga_ou_trunca(self) -> None:
        self.gravar(self.tenant, "0.018", chave=CHAVE)
        for sql in (
            f"UPDATE {LEDGER} SET custo_usd = 0 WHERE tenant_id = %s",
            f"DELETE FROM {LEDGER} WHERE tenant_id = %s",
        ):
            with self.subTest(sql=sql.split()[0]):
                self.erro(VIOLACAO_DE_CHECK, sql, (self.tenant,), "so de acrescentar")
        self.erro(VIOLACAO_DE_CHECK, f"TRUNCATE {LEDGER}", (), "so de acrescentar")
        # E em modo de replicacao tambem: os gatilhos sao `ENABLE ALWAYS`.
        self.cursor.execute("SET LOCAL session_replication_role = replica")
        self.erro(VIOLACAO_DE_CHECK, f"DELETE FROM {LEDGER} WHERE tenant_id = %s", (self.tenant,))
        self.cursor.execute("SET LOCAL session_replication_role = origin")
        self.assertEqual(len(self.linhas(self.tenant)), 1)

    def test_os_gatilhos_sao_always(self) -> None:
        self.cursor.execute(
            "SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = %s::regclass AND NOT tgisinternal "
            "ORDER BY tgname",
            (LEDGER,),
        )
        self.assertEqual(
            [tuple(l) for l in self.cursor.fetchall()],
            [("module_cost_ledger_imutavel", "A"), ("module_cost_ledger_sem_truncate", "A")],
        )

    def test_a_aplicacao_nao_escreve(self) -> None:
        self.como("kamba_app", self.tenant)
        self.erro(
            PRIVILEGIO_INSUFICIENTE,
            f"INSERT INTO {LEDGER} (tenant_id, modulo, rubrica, custo_usd, custo_minor, fx_aoa_per_usd, "
            "idempotency_key) VALUES (%s, 'foto', 'imagem', 1, 913, 913, 'x')",
            (self.tenant,),
        )
        self.erro(
            PRIVILEGIO_INSUFICIENTE,
            "SELECT * FROM platform.module_cost_gravar(%s, 'foto', 'imagem', 1, 'r', 'x', now(), 913)",
            (self.tenant,),
        )

    def test_o_ledger_de_a_e_invisivel_a_b(self) -> None:
        b = factories.tenant(self.cursor)
        factories.contexto(self.cursor, None)
        self.gravar(self.tenant, "0.018")
        self.como("kamba_app", b)
        self.cursor.execute(f"SELECT count(*) FROM {LEDGER} WHERE tenant_id = %s", (self.tenant,))
        self.assertEqual(self.cursor.fetchone()[0], 0)
        self.cursor.execute("SELECT count(*) FROM platform.v_module_cost_month WHERE tenant_id = %s",
                            (self.tenant,))
        self.assertEqual(self.cursor.fetchone()[0], 0)
        self.como("kamba_app", None)
        self.cursor.execute(f"SELECT count(*) FROM {LEDGER}")
        self.assertEqual(self.cursor.fetchone()[0], 0)
        self.como("kamba_app", self.tenant)
        self.cursor.execute(f"SELECT count(*) FROM {LEDGER} WHERE tenant_id = %s", (self.tenant,))
        self.assertEqual(self.cursor.fetchone()[0], 1)

    def test_o_preco_de_teste_so_e_hipotese(self) -> None:
        self.como("kamba_batch")
        self.cursor.execute(
            f"INSERT INTO {PRECOS} (plano, modulo, preco_teste_minor, estado) "
            "VALUES ('entrada_ensaio', 'foto', 1500000, 'hipotese_nao_validada')"
        )
        for estado, modulo, preco in (("decidido", "foto", 1), ("hipotese_nao_validada", "vendedor", 1),
                                      ("hipotese_nao_validada", "social", -1)):
            with self.subTest(estado=estado, modulo=modulo, preco=preco):
                self.erro(
                    VIOLACAO_DE_CHECK,
                    f"INSERT INTO {PRECOS} (plano, modulo, preco_teste_minor, estado) "
                    "VALUES ('entrada_outro', %s, %s, %s)",
                    (modulo, preco, estado),
                )
        self.como("kamba_app", self.tenant)
        self.erro(PRIVILEGIO_INSUFICIENTE, f"SELECT * FROM {PRECOS}")


class TestVistas(_ComTransaccao):
    def _colunas(self, vista: str) -> tuple[str, ...]:
        self.cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'platform' "
            "AND table_name = %s ORDER BY ordinal_position",
            (vista,),
        )
        return tuple(l[0] for l in self.cursor.fetchall())

    def test_as_colunas_sao_a_lista_fechada_e_nenhuma_e_de_pessoa(self) -> None:
        """Criterio 6: «sem `contact_id`, telefone nem conteudo», por igualdade."""
        for vista, esperadas in (("v_module_cost_month", COLUNAS_DO_MES), ("v_h12", COLUNAS_DA_H12)):
            with self.subTest(vista=vista):
                colunas = self._colunas(vista)
                self.assertEqual(colunas, esperadas)
                for coluna in colunas:
                    for proibida in PROIBIDAS:
                        self.assertNotIn(proibida, coluna)
        self.assertEqual(modulos_custo.COLUNAS_DO_MES, COLUNAS_DO_MES)
        self.assertEqual(modulos_custo.COLUNAS_DA_H12, COLUNAS_DA_H12)

    def test_as_vistas_correm_com_a_rls_de_quem_le(self) -> None:
        self.cursor.execute(
            "SELECT relname, reloptions FROM pg_class WHERE relname IN ('v_module_cost_month', 'v_h12') "
            "ORDER BY relname"
        )
        for nome, opcoes in self.cursor.fetchall():
            with self.subTest(vista=nome):
                self.assertIn("security_invoker=true", opcoes)

    def _mes(self, tenant: str) -> dict:
        self.cursor.execute(
            "SELECT mes, modulo, rubrica, unidades, custo_usd, custo_aoa_minor, fx_aoa_per_usd "
            "FROM platform.v_module_cost_month WHERE tenant_id = %s ORDER BY mes, modulo, rubrica",
            (tenant,),
        )
        return {(l[0], l[1], l[2]): tuple(l[3:]) for l in self.cursor.fetchall()}

    def test_o_mes_fecha_a_meia_noite_de_luanda(self) -> None:
        """23:30 UTC do ultimo dia e 00:30 do dia 1 em Luanda (UTC+1): ja e o mes seguinte."""
        self.gravar(self.tenant, "1", quando=dt.datetime(2032, 2, 29, 22, 59, tzinfo=UTC))
        self.gravar(self.tenant, "2", quando=dt.datetime(2032, 2, 29, 23, 0, tzinfo=UTC))
        meses = self._mes(self.tenant)
        self.assertEqual(meses[(dt.date(2032, 2, 1), "foto", "imagem")][1], Decimal("1.000000"))
        self.assertEqual(meses[(dt.date(2032, 3, 1), "foto", "imagem")][1], Decimal("2.000000"))

    def test_soma_por_rubrica_e_converte_ao_cambio_da_sessao(self) -> None:
        self.gravar(self.tenant, "0.018")
        self.gravar(self.tenant, "0.020")
        self.gravar(self.tenant, "0.5", modulo="foto", rubrica="llm")
        meses = self._mes(self.tenant)
        self.assertEqual(meses[(MES, "foto", "imagem")], (2, Decimal("0.038000"), 3469, Decimal("913")))
        self.assertEqual(meses[(MES, "foto", "llm")], (1, Decimal("0.500000"), 45650, Decimal("913")))
        # +7,4% (981): o mesmo custo, a outra taxa, e a taxa na linha.
        self.cursor.execute("SELECT set_config('app.fx_aoa_per_usd', '981', true)")
        meses = self._mes(self.tenant)
        self.assertEqual(meses[(MES, "foto", "llm")], (1, Decimal("0.500000"), 49050, Decimal("981")))
        # Um cambio ilegivel ou nao positivo levanta, e nao cai na omissao.
        for valor in ("abc", "0", "-913"):
            with self.subTest(valor=valor):
                self.cursor.execute("SAVEPOINT cambio")
                self.cursor.execute("SELECT set_config('app.fx_aoa_per_usd', %s, true)", (valor,))
                with self.assertRaises(Exception):
                    self.cursor.execute("SELECT * FROM platform.v_module_cost_month")
                self.cursor.execute("ROLLBACK TO SAVEPOINT cambio")

    def test_a_h12_com_preco_e_sem_preco(self) -> None:
        sem = factories.tenant(self.cursor)
        factories.contexto(self.cursor, None)
        self.cursor.execute("UPDATE platform.tenants SET plano = 'entrada_ensaio' WHERE id = %s", (self.tenant,))
        self.cursor.execute(
            f"INSERT INTO {PRECOS} (plano, modulo, preco_teste_minor, estado) "
            "VALUES ('entrada_ensaio', 'foto', 1500000, 'hipotese_nao_validada')"
        )
        self.gravar(self.tenant, "2.000000")   # 2 x 913 x 100 = 182 600 centimos
        self.gravar(self.tenant, "0.500000", rubrica="llm")
        self.gravar(sem, "1.000000")
        self.cursor.execute(
            "SELECT tenant_id::text, custo_usd, custo_aoa_minor, preco_teste_minor, racio, margem_minor "
            "FROM platform.v_h12 WHERE tenant_id IN (%s, %s) AND mes = %s ORDER BY custo_usd",
            (self.tenant, sem, MES),
        )
        linhas = [tuple(l) for l in self.cursor.fetchall()]
        self.assertEqual(linhas, [
            (sem, Decimal("1.000000"), 91300, None, None, None),
            (self.tenant, Decimal("2.500000"), 228250, 1500000, Decimal("0.152167"), 1271750),
        ])

    def test_a_aplicacao_nao_le_a_h12_e_le_o_seu_mes(self) -> None:
        self.gravar(self.tenant, "0.018")
        self.como("kamba_app", self.tenant)
        self.erro(PRIVILEGIO_INSUFICIENTE, "SELECT * FROM platform.v_h12")
        self.cursor.execute("SELECT count(*) FROM platform.v_module_cost_month WHERE tenant_id = %s",
                            (self.tenant,))
        self.assertEqual(self.cursor.fetchone()[0], 1)


class TestConsolidacao(_ComTransaccao):
    def setUp(self) -> None:
        super().setUp()
        self.canal = factories.canal(self.cursor, self.tenant)
        self.contacto = factories.contacto(self.cursor, self.tenant)
        self.conversa = str(uuid.uuid4())
        self.cursor.execute(
            "INSERT INTO platform.conversations (id, tenant_id, contact_id, channel_id) VALUES (%s, %s, %s, %s)",
            (self.conversa, self.tenant, self.contacto, self.canal),
        )
        factories.contexto(self.cursor, None)

    def _trabalho(self, estado: str, custo: str) -> str:
        campos = {"concluido": (None, f"t/{self.tenant}/foto/v1", 900),
                  "falhado": ("fornecedor", None, None),
                  "a_processar": (None, None, None)}[estado]
        self.cursor.execute(
            "INSERT INTO platform.image_jobs (tenant_id, origem_ref, operacao, provider, idempotency_key, "
            "estado, motivo, versao_ref, latencia_ms, custo_usd, criado_at) "
            "VALUES (%s, %s, 'cutout', 'photoroom', %s, %s, %s, %s, %s, %s, %s) RETURNING image_job_id::text",
            (self.tenant, f"t/{self.tenant}/catalogo/{uuid.uuid4()}", uuid.uuid4().hex, estado, *campos,
             Decimal(custo), DENTRO),
        )
        return self.cursor.fetchone()[0]

    def _chamada(self, vertical: str | None, custo: str | None, resultado: str = "ok") -> None:
        negado = resultado == "destino_negado"
        self.cursor.execute(
            "INSERT INTO dat.llm_call_log (ts, tenant_id, trace_id, vertical, no_grafo, papel, graph_version, "
            " modelo, fornecedor, tokens_in, tokens_out, tokens_cache, custo_usd, latencia_ms, resultado) "
            "VALUES (%s, %s, %s, %s, 'no', 'chat', '1.0.0', 'modelo', 'fornecedor', %s, %s, %s, %s, 1, %s)",
            (DENTRO, self.tenant, str(uuid.uuid4()), vertical, None if negado else 10, None if negado else 10,
             None if negado else 0, None if negado else custo, resultado),
        )

    def _mensagem(self, template: str, categoria: str) -> None:
        self.cursor.execute(
            "INSERT INTO platform.outbound_messages (id, tenant_id, channel_id, contact_id, conversation_id, "
            " idempotency_key, wamid, kind, template_name, state, pricing, created_at, delivered_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'utility', %s, 'delivered', %s::jsonb, %s, %s)",
            (str(uuid.uuid4()), self.tenant, self.canal, self.contacto, self.conversa, f"c-{uuid.uuid4()}",
             f"wamid.ENSAIO{uuid.uuid4().hex[:12]}", template,
             json.dumps({"billable": True, "category": categoria}), DENTRO, DENTRO),
        )

    def _consolidar(self) -> None:
        self.como("kamba_batch")
        self.cursor.execute(modulos_custo.SQL_CONSOLIDAR_IMAGEM, ("913",))
        self.cursor.fetchall()
        self.cursor.execute(modulos_custo.SQL_CONSOLIDAR_LLM, ("913",))
        self.cursor.fetchall()
        self.cursor.execute(modulos_custo.SQL_CONSOLIDAR_MENSAGEM,
                            (["aviso_catalogo"], ["catalogo"], "913"))
        self.cursor.fetchall()
        self.como("admin")

    def test_as_tres_fontes_e_o_que_fica_de_fora(self) -> None:
        concluido = self._trabalho("concluido", "0.018")
        falhado = self._trabalho("falhado", "0.020")
        self._trabalho("a_processar", "0.050")          # vivo: fica de fora
        self._trabalho("concluido", "0")                 # sem custo: fica de fora
        self._chamada("catalogo", "0.001500")
        self._chamada("vendedor", "0.002000")            # nao e modulo
        self._chamada("social", None, "destino_negado")  # recusa: nao aconteceu
        self._mensagem("aviso_catalogo", "utility")
        self._mensagem("outro_template", "marketing")    # o mapa nao o conhece
        self._consolidar()
        linhas = self.linhas(self.tenant)
        self.assertEqual(
            sorted((m, r, c, ref) for m, r, c, _, _, ref in linhas),
            sorted([
                ("foto", "imagem", Decimal("0.018000"), concluido),
                ("foto", "imagem", Decimal("0.020000"), falhado),
                ("catalogo", "llm", Decimal("0.001500"), linhas[[l[1] for l in linhas].index("llm")][5]),
                ("catalogo", "mensagem", Decimal("0.004000"),
                 linhas[[l[1] for l in linhas].index("mensagem")][5]),
            ]),
        )
        # Idempotente: a segunda corrida nao escreve nada.
        self._consolidar()
        self.assertEqual(len(self.linhas(self.tenant)), 4)

    def test_um_custo_ja_consolidado_que_hoje_daria_outro_nao_trava_a_corrida(self) -> None:
        """Achado 1 da revisao adversarial: uma tarifa revista ou um *template*
        remapeado faziam a funcao levantar `23514` em todas as corridas.

        O custo consolidado fica como foi registado, e o resto entra.
        """
        antigo = self._trabalho("concluido", "0.018")
        novo = self._trabalho("concluido", "0.020")
        # A linha de `antigo` ja esta no ledger com outro custo (a tarifa de antes).
        self.gravar(self.tenant, "0.015", chave=f"imagem:{antigo}", ref=antigo)
        self._consolidar()
        self.assertEqual(
            sorted((c, ref) for _, _, c, _, _, ref in self.linhas(self.tenant)),
            [(Decimal("0.015000"), antigo), (Decimal("0.020000"), novo)],
        )

    def test_o_comando_consolida_pelo_mesmo_caminho(self) -> None:
        self._trabalho("concluido", "0.018")
        self.como("kamba_batch")
        dados, codigo = h12.correr(
            argparse.Namespace(comando="consolidar", cambio=None,
                               templates=_RAIZ / "config" / "templates_por_modulo.yaml"),
            self.cursor,
        )
        self.como("admin")
        self.assertEqual(codigo, h12.SAIDA_OK)
        self.assertGreaterEqual(dados["gravadas"]["imagem"], 1)
        self.assertEqual(dados["gravadas"]["mensagem"], 0)  # o mapa do repositorio esta vazio
        self.assertEqual(len(self.linhas(self.tenant)), 1)


class TestExportacao(_ComTransaccao):
    def _ns(self, **campos):  # type: ignore[no-untyped-def]
        return argparse.Namespace(**campos)

    def test_carregar_precos_le_o_registo_sem_deploy(self) -> None:
        self.como("kamba_batch")
        dados, codigo = h12.correr(self._ns(comando="carregar-precos", planos=_RAIZ / "registry" / "plans.yaml"),
                                   self.cursor)
        self.assertEqual(codigo, h12.SAIDA_OK)
        self.cursor.execute(f"SELECT plano, modulo, preco_teste_minor, estado FROM {PRECOS} ORDER BY 1, 2")
        carregados = [tuple(l) for l in self.cursor.fetchall()]
        self.assertEqual(len(carregados), 8)  # quatro planos de um modulo e os quatro do completo
        self.assertIn(("entrada_foto", "foto", 1500000, "hipotese_nao_validada"), carregados)
        self.assertEqual({e for *_, e in carregados}, {"hipotese_nao_validada"})
        self.assertEqual(len(dados["precos"]), 8)
        # Correr outra vez substitui, e nao duplica.
        h12.correr(self._ns(comando="carregar-precos", planos=_RAIZ / "registry" / "plans.yaml"), self.cursor)
        self.cursor.execute(f"SELECT count(*) FROM {PRECOS}")
        self.assertEqual(self.cursor.fetchone()[0], 8)

    def test_exportar_da_o_csv_sem_tenant_id_e_com_o_uso(self) -> None:
        self.cursor.execute("UPDATE platform.tenants SET plano = 'entrada_ensaio' WHERE id = %s", (self.tenant,))
        self.cursor.execute(
            f"INSERT INTO {PRECOS} (plano, modulo, preco_teste_minor, estado) "
            "VALUES ('entrada_ensaio', 'foto', 1500000, 'hipotese_nao_validada')"
        )
        self.cursor.execute(
            "INSERT INTO platform.tenant_usage (tenant_id, chave_limite, periodo, valor) VALUES (%s, 'imagens_mes', %s, 7)",
            (self.tenant, MES),
        )
        self.gravar(self.tenant, "0.180000")
        self.como("kamba_batch")
        texto, codigo = h12.correr(self._ns(comando="exportar", mes=MES, modo=None, cambio=None, saida=None),
                                   self.cursor, ambiente={h12.VARIAVEL_DA_CHAVE: "segredo-de-ensaio"})
        self.assertEqual(codigo, h12.SAIDA_OK)
        self.assertNotIn(self.tenant, texto)
        linhas = list(csv.DictReader(io.StringIO(texto)))
        nossa = [l for l in linhas if l["tenant"] == h12.pseudonimo(b"segredo-de-ensaio", self.tenant)]
        self.assertEqual(nossa, [{
            "tenant": h12.pseudonimo(b"segredo-de-ensaio", self.tenant), "mes": "2032-03", "modulo": "foto",
            "custo_usd": "0.180000", "custo_aoa_minor": "16434", "fx_aoa_per_usd": "913", "uso": "7",
            "preco_teste_minor": "1500000", "estado_do_preco": "hipotese_nao_validada", "racio": "0.010956",
        }])
        # Sem chave, recusa.
        with self.assertRaises(h12.ErroDeUso):
            h12.correr(self._ns(comando="exportar", mes=MES, modo=None, cambio=None, saida=None),
                       self.cursor, ambiente={})

    def test_alertas_e_reconciliacao_sobre_a_base(self) -> None:
        self.cursor.execute("UPDATE platform.tenants SET plano = 'entrada_ensaio' WHERE id = %s", (self.tenant,))
        self.cursor.execute(
            f"INSERT INTO {PRECOS} (plano, modulo, preco_teste_minor, estado) "
            "VALUES ('entrada_ensaio', 'foto', 100000, 'hipotese_nao_validada')"
        )
        self.gravar(self.tenant, "1.000000")  # 91 300 contra 100 000: racio 0,913, critico
        self.como("kamba_batch")
        dados, codigo = h12.correr(
            self._ns(comando="alertas", mes=MES, modo=None, cambio=None,
                     templates=_RAIZ / "config" / "templates_por_modulo.yaml"),
            self.cursor,
        )
        self.assertEqual(codigo, h12.SAIDA_ACHADOS)
        nossos = [a for a in dados["alertas"] if a["tenant_id"] == self.tenant]
        self.assertEqual([(a["tipo"], a["severidade"]) for a in nossos], [("custo_acima_do_preco", "critico")])

        dados, codigo = h12.correr(
            self._ns(comando="reconciliar", mes=MES, litellm=None, painel_imagem=None, meta=None), self.cursor
        )
        # O ledger tem uma imagem que nao veio de `image_jobs`: o desvio e achado.
        self.assertEqual(codigo, h12.SAIDA_ACHADOS)
        self.assertTrue(any(self.tenant in a["chave"] for a in dados["achados"]))


class TestGuardaDeOrcamento(_ComTransaccao):
    def _bd_da_aplicacao(self):  # type: ignore[no-untyped-def]
        self.como("kamba_app", self.tenant)
        return BdDoCursor(self.cursor)

    def test_o_gasto_le_a_imagem_ao_vivo_e_o_resto_do_ledger(self) -> None:
        from kamba_core.foto.orcamento import OrcamentoSobreBase, QuotaComOrcamento
        from kamba_core.foto.servico import Consumo

        factories.entitlement(self.cursor, self.tenant, modulo="foto",
                              limites={"imagens_mes": 40, "custo_max_mes_micro_usd": 50_000})
        factories.contexto(self.cursor, None)
        agora = dt.datetime.now(UTC)
        self.cursor.execute(
            "INSERT INTO platform.image_jobs (tenant_id, origem_ref, operacao, provider, idempotency_key, "
            "estado, versao_ref, latencia_ms, custo_usd) VALUES (%s, %s, 'cutout', 'photoroom', 'k1', "
            "'concluido', %s, 1, 0.030)",
            (self.tenant, f"t/{self.tenant}/catalogo/a", f"t/{self.tenant}/foto/v1"),
        )
        self.gravar(self.tenant, "0.015", rubrica="llm", quando=agora)
        # A imagem consolidada nao se soma duas vezes.
        self.gravar(self.tenant, "0.030", rubrica="imagem", quando=agora)
        # Achado 4 da revisao adversarial: o que **nao** pode entrar na soma —
        # outro modulo no mesmo mes, e o mes anterior no ledger e na imagem.
        mes_passado = agora - dt.timedelta(days=40)
        self.gravar(self.tenant, "9", modulo="social", rubrica="llm", quando=agora)
        self.gravar(self.tenant, "9", rubrica="llm", quando=mes_passado)
        self.cursor.execute(
            "INSERT INTO platform.image_jobs (tenant_id, origem_ref, operacao, provider, idempotency_key, "
            "estado, versao_ref, latencia_ms, custo_usd, criado_at) VALUES (%s, %s, 'cutout', 'photoroom', "
            "'k0', 'concluido', %s, 1, 9, %s)",
            (self.tenant, f"t/{self.tenant}/catalogo/b", f"t/{self.tenant}/foto/v0", mes_passado),
        )
        outro = factories.tenant(self.cursor)
        factories.contexto(self.cursor, None)
        self.gravar(outro, "9", rubrica="llm", quando=agora)
        porta = OrcamentoSobreBase(self._bd_da_aplicacao())
        gasto = porta.gasto(self.tenant)
        self.assertEqual((gasto.orcamento_micro_usd, gasto.gasto_usd), (50_000, Decimal("0.045000")))
        self.assertFalse(gasto.esgotado)

        chamadas = []

        class Quota:
            def consumir(self, tenant_id, chave):  # type: ignore[no-untyped-def]
                chamadas.append(chave)
                return Consumo(aceite=True)

        guarda = QuotaComOrcamento(porta, Quota())
        self.assertTrue(guarda.consumir(self.tenant, "foto:k2").aceite)
        # Mais 0,005 USD de LLM: 50 000 micro-dolares, o tecto. Nao nasce mais nada.
        self.como("admin")
        self.gravar(self.tenant, "0.005", rubrica="llm", quando=agora)
        porta = OrcamentoSobreBase(self._bd_da_aplicacao())
        recusa = QuotaComOrcamento(porta, Quota()).consumir(self.tenant, "foto:k3")
        self.assertEqual((recusa.aceite, recusa.motivo), (False, "orcamento_esgotado"))
        self.assertEqual(chamadas, ["foto:k2"])

    def test_sem_a_chave_do_orcamento_nao_nasce_trabalho(self) -> None:
        from kamba_core.foto.orcamento import OrcamentoSobreBase, QuotaComOrcamento

        factories.entitlement(self.cursor, self.tenant, modulo="foto", limites={"imagens_mes": 40})
        factories.contexto(self.cursor, None)
        recusa = QuotaComOrcamento(OrcamentoSobreBase(self._bd_da_aplicacao()), None).consumir(  # type: ignore[arg-type]
            self.tenant, "foto:k1"
        )
        self.assertEqual((recusa.aceite, recusa.motivo), (False, "sem_orcamento"))

    def test_get_usage_pela_aplicacao(self) -> None:
        from kamba_core.modulos import get_usage, mensagem_orcamento_esgotado

        factories.entitlement(self.cursor, self.tenant, modulo="foto",
                              limites={"imagens_mes": 40, "custo_max_mes_micro_usd": 10_000})
        factories.entitlement(self.cursor, self.tenant, modulo="catalogo",
                              limites={"custo_max_mes_micro_usd": 4_000_000})
        factories.entitlement(self.cursor, self.tenant, modulo="vendedor", limites={"msgs_ai_mes": 10})
        factories.contexto(self.cursor, None)
        self.cursor.execute(
            "INSERT INTO platform.tenant_usage (tenant_id, chave_limite, periodo, valor) "
            "VALUES (%s, 'imagens_mes', platform.ten_periodo(now()), 12)",
            (self.tenant,),
        )
        self.gravar(self.tenant, "0.010", rubrica="llm", quando=dt.datetime.now(UTC))
        usos = get_usage(self._bd_da_aplicacao(), self.tenant)
        self.assertEqual([u.modulo for u in usos], ["catalogo", "foto"])  # o vendedor nao e de entrada
        foto = usos[1]
        self.assertEqual((foto.chave, foto.usado, foto.limite), ("imagens_mes", 12, 40))
        self.assertTrue(foto.gasto.esgotado)
        texto = mensagem_orcamento_esgotado(foto)
        self.assertIn("12 de 40 imagens", texto)
        self.assertIn("100% usado", texto)
        self.assertEqual((usos[0].chave, usos[0].usado, usos[0].limite), (None, None, None))


class TestDowngrade(unittest.TestCase):
    """Desce para a revisao de baixo (lida do ficheiro), com linhas, e volta a subir.

    **Nao exige `em_head()` depois de descer**: com outra revisao por cima, o
    Alembic desce-a primeiro e a base fica na de baixo desta, que e o que se mede.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _contar(self) -> tuple[int, int, int, bool]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT count(*) FROM pg_class WHERE relnamespace = 'platform'::regnamespace AND relname IN "
                      "('module_cost_ledger', 'module_test_prices', 'v_module_cost_month', 'v_h12')")
            objectos = c.fetchone()[0]
            c.execute("SELECT count(*) FROM pg_proc WHERE proname IN ('module_cost_gravar', 'module_cost_ledger_recusar')")
            funcoes = c.fetchone()[0]
            c.execute("SELECT count(*) FROM pg_class WHERE relname = 'v_tenant_cost_daily'")
            vizinha = c.fetchone()[0]
            c.execute("SELECT has_table_privilege('kamba_batch', 'platform.image_jobs', 'SELECT')")
            return objectos, funcoes, vizinha, c.fetchone()[0]
        finally:
            conexao.close()

    def test_desce_com_linhas_e_volta_a_subir(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            tenant = factories.tenant(c)
            factories.contexto(c, None)
            c.execute("SET LOCAL ROLE kamba_batch")
            c.execute("SELECT * FROM platform.module_cost_gravar(%s, 'foto', 'imagem', 0.018, 'r', %s, now(), 913)",
                      (tenant, f"descida-{uuid.uuid4()}"))
            conexao.commit()
        finally:
            conexao.close()
        self.assertEqual(self._contar(), (4, 2, 1, True))
        alembic_ok("downgrade", _literal("down_revision"))
        self.assertEqual(self._contar(), (0, 0, 1, False))
        alembic_ok("upgrade", "head")
        self.assertEqual(self._contar(), (4, 2, 1, True))


if __name__ == "__main__":
    unittest.main()
