"""TEN: entitlements, limites, a matriz do §7.2 e o *hook* da TLS (KAM-009).

Sem PostgreSQL: o cliente de base de dados e injectado, e o que se verifica e o
que a biblioteca faz **a ligacao** — que SQL corre, com que parametros, e o que
faz com cada resposta.

O que **nao** se prova aqui, e onde se prova: que 1 000 chamadas paralelas
contra um limite de 100 aceitam exactamente 100 (criterio 3), que repetir a
chave de idempotencia nao consome duas vezes (criterio 4) e que o mes fecha as
00:00 de `Africa/Luanda` (criterio 5) e tudo SQL — vive em
`platform.ten_consumir`, da revisao `0007`, e prova-se contra um PostgreSQL
real no gate 8. Uma base falsa devolve o que se lhe mandou devolver.

    TestCheckEntitlement   falha fechada: sem linha, sem entitlement,
                           inactivo, estado do tenant
    TestCache              TTL, despejo, e o **teste cruzado**: nunca devolve
                           dados de outro tenant
    TestConsumeLimit       os seis argumentos pela ordem da `0007`, e as duas
                           recusas distinguidas pelo `limite NULL`
    TestInteiro            um tecto mal lido e dinheiro errado: recusa-se
    TestTenantGate         a matriz celula a celula, a precedencia proposta, e
                           o par que uma tabela de um parametro nao tem
    TestMetricas           nenhuma etiqueta leva identificadores
    TestHookDeTool         o passo 2 do `invoke`, com os codigos do §6.5
    TestNaoRegistaNada     nenhum caminho escreve em *log*, nenhum importa
                           controlador
    TestParidadeDoTypeScript
                           o SQL, a matriz, a ordem de precedencia, os nomes
                           das metricas, os codigos e o TTL sao os mesmos de
                           `packages/core-ts/src/ten/`. E o padrao do KAM-005
                           (`TestParidadeDoGuardaDePii`).
"""

from __future__ import annotations

import json
import logging
import re
import unittest
from pathlib import Path

from kamba_core import ten
from kamba_core.ten import (
    ACCOES,
    CATEGORIA_CONTADOR,
    CATEGORIA_TECTO_POR_JANELA,
    CATEGORIA_TECTO_POR_PEDIDO,
    CHAVES_DE_LIMITE,
    CODIGO_ENTITLEMENT_HTTP,
    CODIGO_ENTITLEMENT_TOOL,
    CODIGO_LIMITE,
    ESTADOS_DO_CANAL,
    ESTADOS_DO_TENANT,
    ETIQUETA,
    HTTP_ENTITLEMENT,
    HTTP_LIMITE,
    HTTP_TECTO,
    MARCA_DO_TECTO_ILEGIVEL,
    MAXIMO_DE_ENTRADAS,
    MAXIMO_DE_SERIES,
    METRICA_ENTITLEMENT_NEGADO,
    METRICA_LIMITE_NEGADO,
    NOME_CANONICO,
    REGIME_DO_CANAL,
    REGIME_DO_TENANT,
    REGIMES,
    REGIMES_E_ACCOES,
    SQL_CONSUMIR,
    SQL_ENTITLEMENT,
    SQL_PERIODO,
    SQL_TECTO,
    SQLSTATE_CONFLITO_DE_IDEMPOTENCIA,
    SQLSTATE_LIMITE_ILEGIVEL,
    TTL_POR_OMISSAO_MS,
    CacheDeEntitlements,
    ChaveDeEspecieErrada,
    ChaveDeIdempotenciaInvalida,
    ChaveDesconhecida,
    ConflitoDeIdempotencia,
    Entitlement,
    ErroDeTool,
    EstadoDesconhecido,
    EtiquetaInvalida,
    LimiteIlegivel,
    MetricasDoTen,
    NomeInvalido,
    QuantidadeInvalida,
    RespostaIlegivel,
    Resultado,
    agora_ms,
    check_ceiling,
    check_entitlement,
    consume_limit,
    derivar_chave_de_idempotencia,
    especie_da_chave,
    exigir_consumivel,
    exigir_nome,
    exigir_tecto,
    hook_de_tool,
    inteiro,
    mais_restritivo,
    periodo,
    regime_de,
    sqlstate_de,
    tenant_gate,
)
from kamba_core.tenant_guard import ContextoEmFalta, TenantInvalido

RAIZ = Path(__file__).resolve().parents[3]
TEN_TS = RAIZ / "packages" / "core-ts" / "src" / "ten"
CONSULTAS_TS = TEN_TS / "consultas.ts"
ESTADOS_TS = TEN_TS / "estados.ts"
METRICAS_TS = TEN_TS / "metricas.ts"
ENTITLEMENTS_TS = TEN_TS / "entitlements.ts"
MIDDLEWARE_TS = TEN_TS / "middleware.ts"
REVISAO = RAIZ / "db" / "migrations" / "versions" / "0007_ten_uso_e_limites.py"

A = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60"
B = "7a2d5b11-9c33-4f07-8e21-0c5d9a3b7e14"


def linha_de_entitlement(**parcial: object) -> dict[str, object]:
    """Uma linha de `SQL_ENTITLEMENT` como o PostgreSQL a devolve."""
    linha: dict[str, object] = {
        "estado_tenant": "ativo",
        "tem_linha": True,
        "ativo": True,
        "permitido": True,
    }
    linha.update(parcial)
    return linha


def linha_de_consumo(**parcial: object) -> dict[str, object]:
    """Uma linha de `platform.ten_consumir`. O `pg8000` da `bigint` como int."""
    linha: dict[str, object] = {
        "aceite": True,
        "valor": 1,
        "repetido": False,
        "limite": 100,
    }
    linha.update(parcial)
    return linha


class BaseFalsa:
    """Regista as instrucoes pela ordem em que as recebe."""

    def __init__(self, *respostas: list[dict[str, object]]) -> None:
        self.chamadas: list[tuple[str, tuple[object, ...]]] = []
        self.respostas: list[list[dict[str, object]]] = list(respostas)

    def executar(self, sql: str, parametros=()) -> Resultado:
        self.chamadas.append((sql, tuple(parametros)))
        linhas = self.respostas.pop(0) if self.respostas else []
        return Resultado(linhas=linhas, contagem=len(linhas))


def contexto_de(tenant: str):
    class Ctx:
        tenant_id = tenant

    return Ctx()


class TestCheckEntitlement(unittest.TestCase):
    """Falha fechada: criterio 2."""

    def setUp(self) -> None:
        self.metricas = MetricasDoTen()

    def test_permite_e_corre_o_sql_do_modulo(self) -> None:
        bd = BaseFalsa([linha_de_entitlement()])
        decisao = check_entitlement(bd, A, "vendedor", metricas=self.metricas)
        self.assertTrue(decisao.permitido)
        self.assertIsNone(decisao.motivo)
        self.assertEqual(decisao.estado_tenant, "ativo")
        self.assertEqual(bd.chamadas, [(SQL_ENTITLEMENT, (A, "vendedor"))])
        self.assertEqual(self.metricas.ler(), {})

    def test_zero_linhas_nega_com_sem_tenant(self) -> None:
        """E o caso do contexto de RLS de outro tenant: vazio, nao erro."""
        bd = BaseFalsa([])
        decisao = check_entitlement(bd, A, "vendedor", metricas=self.metricas)
        self.assertFalse(decisao.permitido)
        self.assertEqual(decisao.motivo, "sem_tenant")
        self.assertIsNone(decisao.estado_tenant)
        self.assertEqual(
            self.metricas.ler(), {f"{METRICA_ENTITLEMENT_NEGADO}:vendedor": 1}
        )

    def test_sem_linha_de_entitlement(self) -> None:
        bd = BaseFalsa(
            [linha_de_entitlement(tem_linha=False, ativo=False, permitido=False)]
        )
        decisao = check_entitlement(bd, A, "servicos", metricas=self.metricas)
        self.assertEqual(decisao.motivo, "sem_entitlement")

    def test_entitlement_inactivo(self) -> None:
        bd = BaseFalsa([linha_de_entitlement(ativo=False, permitido=False)])
        decisao = check_entitlement(bd, A, "servicos", metricas=self.metricas)
        self.assertEqual(decisao.motivo, "entitlement_inactivo")

    def test_estado_do_tenant(self) -> None:
        """Quem decidiu foi o SQL: a biblioteca nao tem a lista dos tres."""
        bd = BaseFalsa([linha_de_entitlement(estado_tenant="suspenso", permitido=False)])
        decisao = check_entitlement(bd, A, "vendedor", metricas=self.metricas)
        self.assertEqual(decisao.motivo, "estado_do_tenant")
        self.assertTrue(decisao.ativo)

    def test_le_booleanos_em_texto(self) -> None:
        bd = BaseFalsa(
            [
                {
                    "estado_tenant": "ativo",
                    "tem_linha": "t",
                    "ativo": "true",
                    "permitido": "t",
                }
            ]
        )
        self.assertTrue(check_entitlement(bd, A, "vendedor", metricas=self.metricas).permitido)

    def test_um_estado_que_nao_e_texto_nao_vira_estado(self) -> None:
        bd = BaseFalsa(
            [linha_de_entitlement(estado_tenant=7, permitido=False, ativo=False)]
        )
        decisao = check_entitlement(bd, A, "vendedor", metricas=self.metricas)
        self.assertIsNone(decisao.estado_tenant)

    def test_conta_na_instancia_global_quando_nao_lhe_dao_outra(self) -> None:
        ten.METRICAS.repor()
        try:
            check_entitlement(BaseFalsa([]), A, "vendedor")
            self.assertEqual(
                ten.METRICAS.ler(), {f"{METRICA_ENTITLEMENT_NEGADO}:vendedor": 1}
            )
        finally:
            ten.METRICAS.repor()

    def test_recusa_tenant_que_nao_e_uuid_antes_de_tocar_na_base(self) -> None:
        bd = BaseFalsa()
        with self.assertRaises(TenantInvalido):
            check_entitlement(bd, "nao-e-uuid", "vendedor")
        with self.assertRaises(ContextoEmFalta):
            check_entitlement(bd, None, "vendedor")
        self.assertEqual(bd.chamadas, [])

    def test_recusa_modulo_fora_da_gramatica(self) -> None:
        bd = BaseFalsa()
        for mau in ("Vendedor", 7, "", "_x", "a"):
            with self.subTest(modulo=mau), self.assertRaises(NomeInvalido):
                check_entitlement(bd, A, mau)
        self.assertEqual(bd.chamadas, [])


class TestCache(unittest.TestCase):
    """TTL e isolamento: criterio 6."""

    DECISAO = Entitlement(
        modulo="vendedor",
        permitido=True,
        estado_tenant="ativo",
        ativo=True,
        motivo=None,
    )

    def setUp(self) -> None:
        self.metricas = MetricasDoTen()

    def test_a_segunda_leitura_nao_volta_a_base(self) -> None:
        cache = CacheDeEntitlements()
        bd = BaseFalsa([linha_de_entitlement()])
        check_entitlement(bd, A, "vendedor", cache=cache, metricas=self.metricas)
        check_entitlement(bd, A, "vendedor", cache=cache, metricas=self.metricas)
        self.assertEqual(len(bd.chamadas), 1)

    def test_nunca_devolve_dados_de_outro_tenant(self) -> None:
        """O teste cruzado que o criterio 6 exige."""
        cache = CacheDeEntitlements()
        bd = BaseFalsa(
            [linha_de_entitlement()],
            [linha_de_entitlement(permitido=False, ativo=False, tem_linha=False)],
        )
        de_a = check_entitlement(bd, A, "vendedor", cache=cache, metricas=self.metricas)
        de_b = check_entitlement(bd, B, "vendedor", cache=cache, metricas=self.metricas)
        self.assertTrue(de_a.permitido)
        self.assertFalse(de_b.permitido)
        self.assertEqual(len(bd.chamadas), 2)
        self.assertEqual(bd.chamadas[0][1], (A, "vendedor"))
        self.assertEqual(bd.chamadas[1][1], (B, "vendedor"))
        self.assertTrue(cache.ler(A, "vendedor").permitido)
        self.assertFalse(cache.ler(B, "vendedor").permitido)

    def test_duas_escritas_do_mesmo_tenant_sao_a_mesma_chave(self) -> None:
        cache = CacheDeEntitlements()
        cache.guardar(A, "vendedor", self.DECISAO, agora=0)
        self.assertIsNotNone(cache.ler(A.upper(), "vendedor", agora=1))
        self.assertEqual(cache.tamanho, 1)

    def test_um_modulo_diferente_e_outra_entrada(self) -> None:
        cache = CacheDeEntitlements()
        cache.guardar(A, "vendedor", self.DECISAO, agora=0)
        self.assertIsNone(cache.ler(A, "servicos", agora=1))

    def test_a_entrada_morre_ao_fim_do_ttl(self) -> None:
        self.assertEqual(TTL_POR_OMISSAO_MS, 60_000)
        cache = CacheDeEntitlements()
        cache.guardar(A, "vendedor", self.DECISAO, agora=0)
        self.assertIsNotNone(cache.ler(A, "vendedor", agora=59_999))
        self.assertIsNone(cache.ler(A, "vendedor", agora=60_000))
        self.assertEqual(cache.tamanho, 0)

    def test_depois_do_ttl_volta_a_base(self) -> None:
        cache = CacheDeEntitlements(ttl_ms=10)
        bd = BaseFalsa(
            [linha_de_entitlement()],
            [linha_de_entitlement(ativo=False, permitido=False)],
        )
        self.assertTrue(
            check_entitlement(bd, A, "vendedor", cache=cache, metricas=self.metricas).permitido
        )
        self.assertIsNone(cache.ler(A, "vendedor", agora=agora_ms() + 1_000))
        self.assertFalse(
            check_entitlement(bd, A, "vendedor", cache=cache, metricas=self.metricas).permitido
        )
        self.assertEqual(len(bd.chamadas), 2)

    def test_uma_recusa_em_cache_continua_a_contar(self) -> None:
        cache = CacheDeEntitlements()
        bd = BaseFalsa([linha_de_entitlement(ativo=False, permitido=False)])
        check_entitlement(bd, A, "vendedor", cache=cache, metricas=self.metricas)
        check_entitlement(bd, A, "vendedor", cache=cache, metricas=self.metricas)
        self.assertEqual(
            self.metricas.ler(), {f"{METRICA_ENTITLEMENT_NEGADO}:vendedor": 2}
        )
        self.assertEqual(len(bd.chamadas), 1)

    def test_invalidar_apaga_so_as_entradas_desse_tenant(self) -> None:
        cache = CacheDeEntitlements()
        cache.guardar(A, "vendedor", self.DECISAO, agora=0)
        cache.guardar(A, "servicos", self.DECISAO, agora=0)
        cache.guardar(B, "vendedor", self.DECISAO, agora=0)
        cache.invalidar(A)
        self.assertEqual(cache.tamanho, 1)
        self.assertIsNotNone(cache.ler(B, "vendedor", agora=1))

    def test_repor_esvazia_tudo(self) -> None:
        cache = CacheDeEntitlements()
        cache.guardar(A, "vendedor", self.DECISAO, agora=0)
        cache.repor()
        self.assertEqual(cache.tamanho, 0)

    def test_despejo_expiradas_primeiro_depois_as_mais_antigas(self) -> None:
        cache = CacheDeEntitlements(ttl_ms=1_000, maximo=2)
        cache.guardar(A, "um", self.DECISAO, agora=0)
        cache.guardar(A, "dois", self.DECISAO, agora=0)
        cache.guardar(A, "tres", self.DECISAO, agora=2_000)
        self.assertEqual(cache.tamanho, 1)
        cache.guardar(A, "quatro", self.DECISAO, agora=2_000)
        cache.guardar(A, "cinco", self.DECISAO, agora=2_000)
        self.assertEqual(cache.tamanho, 2)
        self.assertIsNone(cache.ler(A, "tres", agora=2_001))
        self.assertIsNotNone(cache.ler(A, "cinco", agora=2_001))

    def test_ttl_ou_maximo_absurdos_sao_recusados(self) -> None:
        for args in ({"ttl_ms": 0}, {"ttl_ms": -1}, {"maximo": 0}, {"maximo": True}):
            with self.subTest(**args), self.assertRaises(ValueError):
                CacheDeEntitlements(**args)

    def test_o_relogio_por_omissao_anda_para_a_frente(self) -> None:
        antes = agora_ms()
        self.assertGreaterEqual(agora_ms(), antes)


class TestConsumeLimit(unittest.TestCase):
    """Chama a regra, nao a reescreve: criterios 3 e 4."""

    def setUp(self) -> None:
        self.metricas = MetricasDoTen()

    def test_os_seis_argumentos_pela_ordem_da_0007(self) -> None:
        bd = BaseFalsa([linha_de_consumo()])
        quando = "2026-11-30T22:59:59+00:00"
        consume_limit(
            bd,
            A,
            "msgs_ai_mes",
            1,
            "k-1",
            limite=50,
            agora=quando,
            metricas=self.metricas,
        )
        self.assertEqual(
            bd.chamadas,
            [(SQL_CONSUMIR, (A, "msgs_ai_mes", 1, "k-1", 50, quando))],
        )

    def test_sem_tecto_e_sem_relogio_passa_none_nos_dois(self) -> None:
        bd = BaseFalsa([linha_de_consumo()])
        consume_limit(bd, A, "msgs_ai_mes", 2, "k-2", metricas=self.metricas)
        self.assertEqual(
            bd.chamadas[0][1], (A, "msgs_ai_mes", 2, "k-2", None, None)
        )

    def test_aceite(self) -> None:
        bd = BaseFalsa([linha_de_consumo(valor=42, limite=100)])
        consumo = consume_limit(bd, A, "msgs_ai_mes", 1, "k", metricas=self.metricas)
        self.assertTrue(consumo.aceite)
        self.assertEqual(consumo.valor, 42)
        self.assertEqual(consumo.limite, 100)
        self.assertIsNone(consumo.motivo)
        self.assertEqual(self.metricas.ler(), {})

    def test_le_bigint_em_texto_como_o_pg_do_typescript(self) -> None:
        bd = BaseFalsa([linha_de_consumo(valor="42", limite="100")])
        consumo = consume_limit(bd, A, "msgs_ai_mes", 1, "k", metricas=self.metricas)
        self.assertEqual((consumo.valor, consumo.limite), (42, 100))

    def test_repetido_e_aceite_e_nao_conta(self) -> None:
        bd = BaseFalsa([linha_de_consumo(aceite=True, repetido=True, valor=1)])
        consumo = consume_limit(bd, A, "msgs_ai_mes", 1, "k", metricas=self.metricas)
        self.assertTrue(consumo.repetido)
        self.assertTrue(consumo.aceite)
        self.assertIsNone(consumo.motivo)
        self.assertEqual(self.metricas.ler(), {})

    def test_tecto_excedido_conta_na_metrica_da_chave(self) -> None:
        bd = BaseFalsa([linha_de_consumo(aceite=False, valor=100, limite=100)])
        consumo = consume_limit(bd, A, "msgs_ai_mes", 1, "k", metricas=self.metricas)
        self.assertFalse(consumo.aceite)
        self.assertEqual(consumo.motivo, "limite_excedido")
        self.assertEqual(
            self.metricas.ler(), {f"{METRICA_LIMITE_NEGADO}:msgs_ai_mes": 1}
        )

    def test_limite_nulo_e_falta_de_entitlement(self) -> None:
        bd = BaseFalsa([linha_de_consumo(aceite=False, valor=0, limite=None)])
        consumo = consume_limit(bd, A, "msgs_ai_mes", 1, "k", metricas=self.metricas)
        self.assertIsNone(consumo.limite)
        self.assertEqual(consumo.motivo, "sem_entitlement")
        self.assertEqual(self.metricas.ler(), {})

    def test_com_o_modulo_a_falta_conta_no_contador_do_modulo(self) -> None:
        bd = BaseFalsa([linha_de_consumo(aceite=False, valor=0, limite=None)])
        consume_limit(
            bd, A, "msgs_ai_mes", 1, "k", modulo="vendedor", metricas=self.metricas
        )
        self.assertEqual(
            self.metricas.ler(), {f"{METRICA_ENTITLEMENT_NEGADO}:vendedor": 1}
        )

    def test_recusa_quantidades_que_nao_sao_inteiros_positivos(self) -> None:
        bd = BaseFalsa()
        for mau in (0, -1, 1.5, "1", True):
            with self.subTest(quantidade=mau), self.assertRaises(QuantidadeInvalida):
                consume_limit(bd, A, "msgs_ai_mes", mau, "k")
        self.assertEqual(bd.chamadas, [])

    def test_recusa_tecto_negativo_ou_nao_inteiro(self) -> None:
        bd = BaseFalsa()
        for mau in (-1, 0.5, True):
            with self.subTest(limite=mau), self.assertRaises(QuantidadeInvalida):
                consume_limit(bd, A, "msgs_ai_mes", 1, "k", limite=mau)

    def test_recusa_chave_de_idempotencia_vazia(self) -> None:
        bd = BaseFalsa()
        for mau in ("", "   ", 7, None):
            with self.subTest(chave=mau), self.assertRaises(ChaveDeIdempotenciaInvalida):
                consume_limit(bd, A, "msgs_ai_mes", 1, mau)

    def test_recusa_chave_de_limite_fora_da_gramatica(self) -> None:
        with self.assertRaises(NomeInvalido):
            consume_limit(BaseFalsa(), A, "Msgs", 1, "k")

    def test_zero_linhas_e_erro_e_nunca_aceite(self) -> None:
        with self.assertRaises(RespostaIlegivel):
            consume_limit(BaseFalsa([]), A, "msgs_ai_mes", 1, "k")


class TestInteiro(unittest.TestCase):
    """Um tecto mal lido e dinheiro errado: recusa-se em vez de adivinhar."""

    def test_aceita_inteiro_e_texto_decimal(self) -> None:
        self.assertEqual(inteiro("x", 7), 7)
        self.assertEqual(inteiro("x", "-12"), -12)
        self.assertEqual(inteiro("x", 9_007_199_254_740_993), 9_007_199_254_740_993)

    def test_recusa_o_que_nao_se_le_sem_adivinhar(self) -> None:
        for mau in (1.5, "1.5", "", None, {}, True, False):
            with self.subTest(valor=mau), self.assertRaises(RespostaIlegivel):
                inteiro("x", mau)


class TestPeriodo(unittest.TestCase):
    """Pergunta-se a base; nao se calcula o mes em Python."""

    def test_passa_o_instante_e_devolve_o_que_a_base_disse(self) -> None:
        bd = BaseFalsa([{"periodo": "2026-11-01"}])
        quando = "2026-11-30T22:59:59+00:00"
        self.assertEqual(periodo(bd, quando), "2026-11-01")
        self.assertEqual(bd.chamadas, [(SQL_PERIODO, (quando,))])

    def test_sem_instante_passa_none(self) -> None:
        """M3: e o `coalesce` do SQL que transforma o `None` em `now()`.

        Era aqui que os dois lados divergiam: sem `coalesce`, a funcao recebia
        `NULL`, devolvia `NULL`, e este lado entregava `None` em silencio
        enquanto o TypeScript levantava. O `None` continua a ir — o que mudou
        e que ha um `coalesce` do outro lado para o apanhar.
        """
        bd = BaseFalsa([{"periodo": "2026-12-01"}])
        self.assertEqual(periodo(bd), "2026-12-01")
        self.assertEqual(bd.chamadas[0][1], (None,))
        self.assertIn("coalesce(%s, now())", bd.chamadas[0][0])

    def test_os_dois_caminhos_correm_o_mesmo_sql(self) -> None:
        """Com instante e sem ele: uma consulta so, e nao duas versoes."""
        com = BaseFalsa([{"periodo": "2026-11-01"}])
        periodo(com, "2026-11-30T22:59:59+00:00")
        sem = BaseFalsa([{"periodo": "2026-12-01"}])
        periodo(sem)
        self.assertEqual(com.chamadas[0][0], sem.chamadas[0][0])
        self.assertEqual(com.chamadas[0][0], SQL_PERIODO)

    def test_uma_resposta_sem_periodo_levanta(self) -> None:
        with self.assertRaises(RespostaIlegivel):
            periodo(BaseFalsa([{"outra": 1}]))
        with self.assertRaises(RespostaIlegivel):
            periodo(BaseFalsa([]))


class TestRegistoDeChaves(unittest.TestCase):
    """A especie de cada chave e **um facto do registo**, e nao uma convencao.

    O `x-kamba-consumivel` existia no `registry/entitlement_keys.schema.json`
    e **nada o lia**. A tabela `CHAVES_DE_LIMITE` passa a te-lo por extenso, e
    este e o teste que a prende ao ficheiro: le o registo e confronta chave a
    chave. Uma chave acrescentada la e nao acrescentada aqui cai aqui.
    """

    @classmethod
    def setUpClass(cls) -> None:
        caminho = RAIZ / "registry" / "entitlement_keys.schema.json"
        cls.registo = json.loads(caminho.read_text(encoding="utf-8"))

    def test_as_dez_chaves_sao_as_mesmas(self) -> None:
        do_registo = sorted(self.registo["properties"])
        self.assertEqual(len(do_registo), 10)
        self.assertEqual(sorted(CHAVES_DE_LIMITE), do_registo)

    def test_a_categoria_e_o_consumivel_vem_do_registo(self) -> None:
        for nome, propriedade in self.registo["properties"].items():
            with self.subTest(chave=nome):
                nossa = CHAVES_DE_LIMITE[nome]
                self.assertEqual(nossa.nome, nome)
                self.assertEqual(nossa.categoria, propriedade["x-kamba-categoria"])
                self.assertEqual(nossa.consumivel, propriedade["x-kamba-consumivel"])

    def test_as_tres_categorias_sao_as_que_o_registo_declara(self) -> None:
        declaradas = sorted(self.registo["x-kamba-categorias"])
        self.assertEqual(
            declaradas,
            sorted(
                (CATEGORIA_CONTADOR, CATEGORIA_TECTO_POR_PEDIDO, CATEGORIA_TECTO_POR_JANELA)
            ),
        )

    def test_so_os_contadores_sao_consumiveis(self) -> None:
        for chave in CHAVES_DE_LIMITE.values():
            with self.subTest(chave=chave.nome):
                self.assertEqual(
                    chave.consumivel, chave.categoria == CATEGORIA_CONTADOR
                )

    def test_cinco_baldes_tres_tectos_por_pedido_dois_por_janela(self) -> None:
        contagem: dict[str, int] = {}
        for chave in CHAVES_DE_LIMITE.values():
            contagem[chave.categoria] = contagem.get(chave.categoria, 0) + 1
        self.assertEqual(
            contagem,
            {
                CATEGORIA_CONTADOR: 5,
                CATEGORIA_TECTO_POR_PEDIDO: 3,
                CATEGORIA_TECTO_POR_JANELA: 2,
            },
        )

    def test_uma_chave_fora_do_registo_nao_se_adivinha(self) -> None:
        with self.assertRaises(ChaveDesconhecida):
            especie_da_chave("msgs_ai_semana")
        # E continua a passar pela gramatica primeiro.
        with self.assertRaises(NomeInvalido):
            especie_da_chave("Msgs-AI")
        # Nomes herdados de um prototipo casam a gramatica. Em Python um
        # `dict` nao os tem, mas o espelho em TypeScript sim — e la a tabela
        # consulta-se com `Object.hasOwn`. O caso fica coberto dos dois lados.
        for herdada in ("constructor", "tostring", "valueof"):
            with self.subTest(chave=herdada), self.assertRaises(ChaveDesconhecida):
                especie_da_chave(herdada)


class TestEspecieDaChave(unittest.TestCase):
    """Cada funcao recusa a chave da outra especie. Nao se corrige a correr."""

    def test_consumir_um_tecto_por_pedido_levanta_antes_da_base(self) -> None:
        for chave in (
            "valor_max_pedido_minor",
            "manual_max_minor",
            "manual_dupla_acima_minor",
            "manual_daily_max_minor",
            "manual_max_por_contacto_24h",
        ):
            bd = BaseFalsa([linha_de_consumo()])
            with self.subTest(chave=chave), self.assertRaises(ChaveDeEspecieErrada):
                consume_limit(bd, A, chave, 1, "k")
            self.assertEqual(bd.chamadas, [], "nao chegou a tocar na base")

    def test_perguntar_cabimento_a_um_balde_levanta(self) -> None:
        for chave in ("msgs_ai_mes", "marcacoes_mes", "imagens_mes"):
            bd = BaseFalsa([{"tecto": 1}])
            with self.subTest(chave=chave), self.assertRaises(ChaveDeEspecieErrada):
                check_ceiling(bd, A, chave, 1)
            self.assertEqual(bd.chamadas, [])

    def test_as_duas_chaves_de_janela_nao_tem_caminho_neste_ticket(self) -> None:
        """E dizem-no a dizer porque, em vez de responderem mal.

        O agregado da janela nao esta em `platform.tenant_usage` — a chave
        dessa tabela e mensal e nao tem a dimensao do contacto. Vem de
        `manual_confirmations` (`04` §4.2 M-6), que este ticket nao constroi.
        """
        for chave in ("manual_daily_max_minor", "manual_max_por_contacto_24h"):
            with self.subTest(chave=chave):
                with self.assertRaises(ChaveDeEspecieErrada) as apanhado:
                    check_ceiling(BaseFalsa(), A, chave, 1)
                self.assertIn("manual_confirmations", str(apanhado.exception))

    def test_as_tres_do_tecto_por_pedido_passam(self) -> None:
        for chave in (
            "valor_max_pedido_minor",
            "manual_max_minor",
            "manual_dupla_acima_minor",
        ):
            with self.subTest(chave=chave):
                self.assertEqual(exigir_tecto(chave), chave)

    def test_os_cinco_baldes_passam_no_consumo(self) -> None:
        for chave in (
            "msgs_ai_mes",
            "marcacoes_mes",
            "imagens_mes",
            "posts_mes",
            "orcamentos_mes",
        ):
            with self.subTest(chave=chave):
                self.assertEqual(exigir_consumivel(chave), chave)


class TestCheckCeiling(unittest.TestCase):
    """«Este valor cabe?» — e **nada** disto escreve."""

    def setUp(self) -> None:
        self.metricas = MetricasDoTen()

    def test_corre_o_sql_do_tecto_com_o_tenant_e_a_chave(self) -> None:
        bd = BaseFalsa([{"tecto": 5_000_000}])
        tecto = check_ceiling(bd, A, "valor_max_pedido_minor", 4_999_999)
        self.assertEqual(bd.chamadas, [(SQL_TECTO, (A, "valor_max_pedido_minor"))])
        self.assertTrue(tecto.cabe)
        self.assertEqual(tecto.tecto, 5_000_000)
        self.assertEqual(tecto.valor, 4_999_999)
        self.assertIsNone(tecto.motivo)

    def test_o_valor_igual_ao_tecto_cabe(self) -> None:
        bd = BaseFalsa([{"tecto": 100}])
        self.assertTrue(check_ceiling(bd, A, "manual_max_minor", 100).cabe)

    def test_um_acima_do_tecto_nao_cabe_e_conta(self) -> None:
        bd = BaseFalsa([{"tecto": 100}])
        tecto = check_ceiling(bd, A, "manual_max_minor", 101, metricas=self.metricas)
        self.assertFalse(tecto.cabe)
        self.assertEqual(tecto.motivo, "tecto_excedido")
        self.assertEqual(
            self.metricas.ler(), {f"{METRICA_LIMITE_NEGADO}:manual_max_minor": 1}
        )

    def test_sem_linha_activa_que_declare_a_chave_nega(self) -> None:
        """Falha fechada, criterio 2: `NULL` nao e «sem limite»."""
        for resposta in ([{"tecto": None}], [{}], []):
            with self.subTest(resposta=resposta):
                tecto = check_ceiling(
                    BaseFalsa(resposta), A, "manual_max_minor", 1
                )
                self.assertFalse(tecto.cabe)
                self.assertIsNone(tecto.tecto)
                self.assertEqual(tecto.motivo, "sem_entitlement")

    def test_a_falta_conta_no_contador_do_modulo_quando_lho_dizem(self) -> None:
        bd = BaseFalsa([{"tecto": None}])
        check_ceiling(
            bd, A, "manual_max_minor", 1, modulo="vendedor", metricas=self.metricas
        )
        self.assertEqual(
            self.metricas.ler(), {f"{METRICA_ENTITLEMENT_NEGADO}:vendedor": 1}
        )

    def test_le_o_bigint_em_texto_como_o_pg_do_typescript(self) -> None:
        bd = BaseFalsa([{"tecto": "5000000"}])
        self.assertEqual(check_ceiling(bd, A, "manual_max_minor", 1).tecto, 5_000_000)

    def test_um_tecto_ilegivel_levanta_em_vez_de_adivinhar(self) -> None:
        with self.assertRaises(RespostaIlegivel):
            check_ceiling(BaseFalsa([{"tecto": "cinco"}]), A, "manual_max_minor", 1)

    def test_zero_cabe_em_qualquer_tecto_e_negativo_levanta(self) -> None:
        self.assertTrue(check_ceiling(BaseFalsa([{"tecto": 0}]), A, "manual_max_minor", 0).cabe)
        for mau in (-1, 1.5, True, None, "10"):
            with self.subTest(valor=mau), self.assertRaises(QuantidadeInvalida):
                check_ceiling(BaseFalsa([{"tecto": 10}]), A, "manual_max_minor", mau)

    def test_recusa_um_tenant_que_nao_e_uuid_antes_de_tocar_na_base(self) -> None:
        bd = BaseFalsa([{"tecto": 1}])
        with self.assertRaises(TenantInvalido):
            check_ceiling(bd, "nao-e-uuid", "manual_max_minor", 1)
        self.assertEqual(bd.chamadas, [])

    def test_o_limiar_da_dupla_verificacao_e_a_mesma_comparacao(self) -> None:
        """`manual_dupla_acima_minor`: `cabe = False` nao e uma recusa.

        O registo escreve-o — «o unico tecto por pedido cuja comparacao NAO
        nega». A funcao devolve o facto; quem chama e que decide que acima do
        limiar o pedido exige o segundo confirmador (`04` §4.2 M-5).
        """
        bd = BaseFalsa([{"tecto": 2_000_000}])
        acima = check_ceiling(bd, A, "manual_dupla_acima_minor", 2_000_001)
        self.assertFalse(acima.cabe)
        self.assertEqual(acima.tecto, 2_000_000)


class TestDerivacaoDaChaveDeIdempotencia(unittest.TestCase):
    """C1: o que o cliente manda e **um componente**, nunca a chave."""

    #: Vector fixo, confrontado com o do TypeScript pelo teste de paridade.
    VECTOR = "aecad9b30b59f9439b80d87246a2a8318a3b5f766e899faef810168f503e3df0"

    def test_o_vector_conhecido(self) -> None:
        self.assertEqual(
            derivar_chave_de_idempotencia(
                "ten.v1", A, "vendedor", "msgs_ai_mes", "req-1"
            ),
            self.VECTOR,
        )

    def test_e_determinista_e_hexadecimal(self) -> None:
        uma = derivar_chave_de_idempotencia("ten.v1", A, "vendedor", "msgs_ai_mes", "x")
        outra = derivar_chave_de_idempotencia("ten.v1", A, "vendedor", "msgs_ai_mes", "x")
        self.assertEqual(uma, outra)
        self.assertRegex(uma, r"^[0-9a-f]{64}$")

    def test_cada_componente_muda_a_chave(self) -> None:
        base = ("ten.v1", A, "vendedor", "msgs_ai_mes", "x")
        vistas = {derivar_chave_de_idempotencia(*base)}
        for indice, outro in enumerate((B, "servicos", "marcacoes_mes", "y"), start=1):
            trocado = list(base)
            trocado[indice] = outro
            vistas.add(derivar_chave_de_idempotencia(*trocado))
        self.assertEqual(len(vistas), 5)

    def test_o_separador_impede_a_colisao_por_concatenacao(self) -> None:
        """`ab` + `c` e `a` + `bc` nao podem dar a mesma chave."""
        self.assertNotEqual(
            derivar_chave_de_idempotencia("ab", "c"),
            derivar_chave_de_idempotencia("a", "bc"),
        )

    def test_componentes_vazios_ou_que_nao_sao_texto_levantam(self) -> None:
        for maus in ((), ("",), ("  ",), ("a", None), ("a", 7)):
            with self.subTest(maus=maus), self.assertRaises(ChaveDeIdempotenciaInvalida):
                derivar_chave_de_idempotencia(*maus)


class TestSqlstateEConflito(unittest.TestCase):
    """O `KA002` da `0007` e um conflito do pedido, e nao um limite."""

    def test_le_o_sqlstate_das_tres_formas_conhecidas(self) -> None:
        class ComAtributo(Exception):
            sqlstate = "KA002"

        class ComCode(Exception):
            code = "KA002"

        do_pg8000 = Exception({"S": "ERROR", "C": "KA002", "M": "conflito"})
        for erro in (ComAtributo(), ComCode(), do_pg8000):
            with self.subTest(erro=type(erro).__name__):
                self.assertEqual(sqlstate_de(erro), "KA002")

    def test_o_que_nao_e_sqlstate_nao_se_inventa(self) -> None:
        class Enganador(Exception):
            code = "nao-e-um-sqlstate"

        self.assertIsNone(sqlstate_de(Enganador()))
        self.assertIsNone(sqlstate_de(Exception("sem nada")))
        self.assertIsNone(sqlstate_de(Exception({"C": 404})))

    def test_o_ka002_vira_conflito_de_idempotencia(self) -> None:
        class BaseQueLevanta:
            def executar(self, sql, parametros=()):
                erro = RuntimeError("conflito")
                erro.sqlstate = "KA002"  # type: ignore[attr-defined]
                raise erro

        with self.assertRaises(ConflitoDeIdempotencia) as apanhado:
            consume_limit(BaseQueLevanta(), A, "msgs_ai_mes", 1, "k")
        self.assertIsInstance(apanhado.exception.__cause__, RuntimeError)
        # E a mensagem nao repete nem a chave nem a quantidade (`OBS-I`).
        self.assertNotIn("msgs_ai_mes", str(apanhado.exception))

    def test_o_23514_e_os_outros_sobem_como_vieram(self) -> None:
        """So se traduz o que se reconhece; o resto nao se disfarca."""
        for estado in ("23514", "22023", "40001"):
            class BaseQueLevanta:
                def executar(self, sql, parametros=(), _e=estado):
                    erro = RuntimeError("da base")
                    erro.sqlstate = _e  # type: ignore[attr-defined]
                    raise erro

            with self.subTest(sqlstate=estado), self.assertRaises(RuntimeError) as a:
                consume_limit(BaseQueLevanta(), A, "msgs_ai_mes", 1, "k")
            self.assertNotIsInstance(a.exception, ConflitoDeIdempotencia)

    def test_o_nome_do_sqlstate_e_o_da_0007(self) -> None:
        self.assertEqual(SQLSTATE_CONFLITO_DE_IDEMPOTENCIA, "KA002")
        self.assertEqual(SQLSTATE_LIMITE_ILEGIVEL, "22023")


def _base_que_levanta(estado: str, mensagem: str = "da base"):
    """Uma base que levanta um erro de controlador com um `SQLSTATE`."""

    class BaseQueLevanta:
        def executar(self, sql, parametros=()):
            erro = RuntimeError(mensagem)
            erro.sqlstate = estado  # type: ignore[attr-defined]
            raise erro

    return BaseQueLevanta()


class TestLimiteIlegivel(unittest.TestCase):
    """O `22023` da `ten_tecto`: um dado corrompido nao e «nao cabe».

    A `platform.ten_tecto` recusa-se a adivinhar um `limites` que nao seja um
    inteiro nao negativo, e levanta em vez de ignorar a linha — ignora-la
    tirava um modulo do minimo, e o minimo de menos modulos e **maior**.
    Deste lado, le-lo como recusa de tecto diria ao tenant que o pedido dele e
    grande demais quando o que ha e um dado por corrigir.
    """

    MENSAGEM = (
        "ten_tecto: a chave manual_max_minor tem um limite que nao e um "
        "inteiro em entitlements"
    )

    def test_o_22023_no_tecto_vira_limite_ilegivel(self) -> None:
        with self.assertRaises(LimiteIlegivel) as apanhado:
            check_ceiling(
                _base_que_levanta("22023", self.MENSAGEM), A, "manual_max_minor", 1
            )
        self.assertIsInstance(apanhado.exception.__cause__, RuntimeError)

    def test_nao_e_recusa_e_nao_conta_como_limite_negado(self) -> None:
        """Um limite ilegivel **nao** e um `ten_limit_denied_total`."""
        metricas = MetricasDoTen()
        with self.assertRaises(LimiteIlegivel):
            check_ceiling(
                _base_que_levanta("22023", self.MENSAGEM),
                A,
                "manual_max_minor",
                1,
                modulo="vendedor",
                metricas=metricas,
            )
        self.assertEqual(metricas.ler(), {})

    def test_no_tecto_traduz_sem_olhar_para_a_mensagem(self) -> None:
        """O `SQL_TECTO` nao passa instante: o `22023` so pode ser este."""
        with self.assertRaises(LimiteIlegivel):
            check_ceiling(
                _base_que_levanta("22023", "outra mensagem qualquer"),
                A,
                "manual_max_minor",
                1,
            )

    def test_no_consumo_traduz_so_o_que_a_mensagem_nomeia(self) -> None:
        """A `ten_consumir` usa o mesmo `22023` na guarda de `p_agora`.

        Um instante absurdo **nao** e um limite ilegivel, e dizer que e seria
        inventar uma causa. Distingue-se pela mensagem, que e o unico sinal
        que ha; e quando nao se reconhece, o erro original sobe inalterado.
        """
        with self.assertRaises(LimiteIlegivel):
            consume_limit(
                _base_que_levanta("22023", self.MENSAGEM), A, "msgs_ai_mes", 1, "k"
            )
        with self.assertRaises(RuntimeError) as apanhado:
            consume_limit(
                _base_que_levanta("22023", "ten_consumir: instante fora da janela"),
                A,
                "msgs_ai_mes",
                1,
                "k",
            )
        self.assertNotIsInstance(apanhado.exception, LimiteIlegivel)

    def test_no_tecto_o_que_nao_e_22023_sobe_como_veio(self) -> None:
        """Traduzir de mais era disfarcar um erro que nao se percebeu."""
        for estado in ("23514", "KA002", "40001"):
            with self.subTest(sqlstate=estado), self.assertRaises(RuntimeError) as a:
                check_ceiling(
                    _base_que_levanta(estado), A, "manual_max_minor", 1
                )
            self.assertNotIsInstance(a.exception, LimiteIlegivel)
            self.assertEqual(str(a.exception), "da base")

    def test_a_mensagem_nao_repete_o_valor_guardado(self) -> None:
        """`OBS-I`: um limite e um numero de negocio e nao vai para o registo."""
        with self.assertRaises(LimiteIlegivel) as apanhado:
            check_ceiling(
                _base_que_levanta("22023", self.MENSAGEM), A, "manual_max_minor", 1
            )
        texto = str(apanhado.exception)
        self.assertNotIn("manual_max_minor", texto)
        self.assertIn("22023", texto)

    def test_nao_e_uma_resposta_ilegivel(self) -> None:
        """Formas diferentes, erros diferentes: um e a resposta, outro o dado."""
        self.assertFalse(issubclass(LimiteIlegivel, RespostaIlegivel))
        self.assertFalse(issubclass(RespostaIlegivel, LimiteIlegivel))


class TestTenantGate(unittest.TestCase):
    """A matriz do §7.2 com os dois estados: criterio 6."""

    #: As seis linhas, escritas outra vez a partir da tabela do documento. Nao
    #: se importa o `REGIMES_E_ACCOES`: um teste que le a tabela que verifica
    #: nao verifica nada.
    ESPERADO = {
        "pendente": {
            "registar_entrada": True,
            "processar_entrada": False,
            "responder_sessao": False,
            "enviar_template_utilidade": False,
            "enviar_template_marketing": False,
            "mensagem_estatica": False,
            "mensagem_de_teste": True,
        },
        "ativo": {
            "registar_entrada": True,
            "processar_entrada": True,
            "responder_sessao": True,
            "enviar_template_utilidade": True,
            "enviar_template_marketing": True,
            "mensagem_estatica": True,
            "mensagem_de_teste": True,
        },
        "restrito": {
            "registar_entrada": True,
            "processar_entrada": True,
            "responder_sessao": True,
            "enviar_template_utilidade": False,
            "enviar_template_marketing": False,
            "mensagem_estatica": True,
            "mensagem_de_teste": False,
        },
        "desligado": {
            "registar_entrada": False,
            "processar_entrada": False,
            "responder_sessao": False,
            "enviar_template_utilidade": False,
            "enviar_template_marketing": False,
            "mensagem_estatica": False,
            "mensagem_de_teste": False,
        },
        "suspenso": {
            "registar_entrada": True,
            "processar_entrada": False,
            "responder_sessao": False,
            "enviar_template_utilidade": False,
            "enviar_template_marketing": False,
            "mensagem_estatica": True,
            "mensagem_de_teste": False,
        },
        "encerrado": {
            "registar_entrada": True,
            "processar_entrada": False,
            "responder_sessao": False,
            "enviar_template_utilidade": False,
            "enviar_template_marketing": False,
            "mensagem_estatica": False,
            "mensagem_de_teste": False,
        },
    }

    def test_os_dominios_tem_cinco_e_seis_estados(self) -> None:
        """E por isso e que uma tabela de seis linhas nao chega."""
        self.assertEqual(len(ESTADOS_DO_TENANT), 5)
        self.assertEqual(len(ESTADOS_DO_CANAL), 6)
        self.assertEqual(len(REGIMES), 6)
        self.assertNotIn("desligado", ESTADOS_DO_TENANT)
        self.assertNotIn("onboarding", ESTADOS_DO_CANAL)

    def test_cada_estado_tem_regime_e_cada_regime_e_uma_linha(self) -> None:
        for estado in ESTADOS_DO_TENANT:
            self.assertIn(REGIME_DO_TENANT[estado], REGIMES)
        for estado in ESTADOS_DO_CANAL:
            self.assertIn(REGIME_DO_CANAL[estado], REGIMES)
        self.assertEqual(sorted(REGIMES_E_ACCOES), sorted(REGIMES))
        for regime in REGIMES:
            self.assertEqual(sorted(REGIMES_E_ACCOES[regime]), sorted(ACCOES))

    #: O regime de cada um dos 30 pares, escrito **a mao** a partir da regra
    #: de precedencia, e nao calculado com ela.
    #:
    #: Um teste que corresse `regime_de` para construir o esperado verificava
    #: que a funcao e igual a si propria. Esta tabela e a leitura humana de
    #: «`desligado` ganha de tudo; as outras cinco ordenam-se do mais
    #: restritivo para o menos», linha a linha, e e o que apanha uma troca de
    #: duas posicoes em `REGIMES`.
    REGIME_DO_PAR = {
        ("onboarding", "pendente"): "pendente",
        ("onboarding", "ativo"): "pendente",
        ("onboarding", "restrito"): "pendente",
        ("onboarding", "desligado"): "desligado",
        ("onboarding", "suspenso"): "suspenso",
        ("onboarding", "encerrado"): "encerrado",
        ("ativo", "pendente"): "pendente",
        ("ativo", "ativo"): "ativo",
        ("ativo", "restrito"): "restrito",
        ("ativo", "desligado"): "desligado",
        ("ativo", "suspenso"): "suspenso",
        ("ativo", "encerrado"): "encerrado",
        ("restrito", "pendente"): "pendente",
        ("restrito", "ativo"): "restrito",
        ("restrito", "restrito"): "restrito",
        ("restrito", "desligado"): "desligado",
        ("restrito", "suspenso"): "suspenso",
        ("restrito", "encerrado"): "encerrado",
        ("suspenso", "pendente"): "suspenso",
        ("suspenso", "ativo"): "suspenso",
        ("suspenso", "restrito"): "suspenso",
        ("suspenso", "desligado"): "desligado",
        ("suspenso", "suspenso"): "suspenso",
        ("suspenso", "encerrado"): "encerrado",
        ("encerrado", "pendente"): "encerrado",
        ("encerrado", "ativo"): "encerrado",
        ("encerrado", "restrito"): "encerrado",
        ("encerrado", "desligado"): "desligado",
        ("encerrado", "suspenso"): "encerrado",
        ("encerrado", "encerrado"): "encerrado",
    }

    def test_a_ordem_de_precedencia_e_a_proposta(self) -> None:
        """`desligado` a cabeca: e transporte, e nao politica."""
        self.assertEqual(
            REGIMES,
            ("desligado", "encerrado", "suspenso", "pendente", "restrito", "ativo"),
        )
        self.assertEqual(mais_restritivo("ativo", "encerrado"), "encerrado")
        self.assertEqual(mais_restritivo("encerrado", "ativo"), "encerrado")
        self.assertEqual(mais_restritivo("restrito", "pendente"), "pendente")
        self.assertEqual(mais_restritivo("ativo", "ativo"), "ativo")
        # A correccao: `desligado` ganha a todos os outros cinco, nos dois
        # sentidos. Antes perdia para `encerrado` e para `suspenso`.
        for outro in ("encerrado", "suspenso", "pendente", "restrito", "ativo"):
            with self.subTest(outro=outro):
                self.assertEqual(mais_restritivo("desligado", outro), "desligado")
                self.assertEqual(mais_restritivo(outro, "desligado"), "desligado")

    def test_o_caso_que_a_revisao_mediu(self) -> None:
        """Tenant `suspenso` + canal `desligado` **nao** autoriza enviar.

        Era o defeito: a linha `suspenso` permite a mensagem estatica, e com
        `suspenso` a ganhar o gate autorizava um envio por um canal que o
        §7.2 diz removido. Nenhum estado de politica faz reaparecer um
        transporte que nao existe.
        """
        decisao = tenant_gate("suspenso", "desligado", "mensagem_estatica")
        self.assertEqual(decisao.regime, "desligado")
        self.assertFalse(decisao.permitido)
        self.assertEqual(decisao.origem, "canal")
        # E nenhuma das sete accoes passa, venha o tenant de onde vier.
        for estado in ESTADOS_DO_TENANT:
            for accao in ACCOES:
                with self.subTest(estado_tenant=estado, accao=accao):
                    self.assertFalse(tenant_gate(estado, "desligado", accao).permitido)

    def test_a_matriz_completa_dos_210_casos(self) -> None:
        """5 estados de tenant x 6 de canal x 7 accoes, um a um.

        Nao so o par que falhou: a tabela inteira, contra o regime escrito a
        mao em `REGIME_DO_PAR` e a celula escrita a mao em `ESPERADO`.
        """
        casos = 0
        for estado_tenant in ESTADOS_DO_TENANT:
            for estado_canal in ESTADOS_DO_CANAL:
                regime = self.REGIME_DO_PAR[(estado_tenant, estado_canal)]
                self.assertEqual(regime_de(estado_tenant, estado_canal), regime)
                for accao in ACCOES:
                    casos += 1
                    with self.subTest(
                        estado_tenant=estado_tenant,
                        estado_canal=estado_canal,
                        accao=accao,
                    ):
                        self.assertEqual(
                            tenant_gate(estado_tenant, estado_canal, accao).permitido,
                            self.ESPERADO[regime][accao],
                        )
        self.assertEqual(casos, 5 * 6 * 7)

    def test_nenhum_par_com_canal_desligado_autoriza_saida(self) -> None:
        """A propriedade que a precedencia passa a garantir, por extenso."""
        saidas = (
            "processar_entrada",
            "responder_sessao",
            "enviar_template_utilidade",
            "enviar_template_marketing",
            "mensagem_estatica",
            "mensagem_de_teste",
        )
        for estado_tenant in ESTADOS_DO_TENANT:
            for accao in saidas:
                with self.subTest(estado_tenant=estado_tenant, accao=accao):
                    self.assertFalse(
                        tenant_gate(estado_tenant, "desligado", accao).permitido
                    )

    def test_o_par_que_uma_tabela_de_um_parametro_nao_tem(self) -> None:
        decisao = tenant_gate("ativo", "desligado", "registar_entrada")
        self.assertEqual(decisao.regime, "desligado")
        self.assertFalse(decisao.permitido)
        self.assertEqual(decisao.origem, "canal")

    def test_o_inverso_manda_o_tenant(self) -> None:
        decisao = tenant_gate("suspenso", "ativo", "mensagem_estatica")
        self.assertEqual(decisao.regime, "suspenso")
        self.assertTrue(decisao.permitido)
        self.assertEqual(decisao.origem, "tenant")

    def test_onboarding_e_pendente_sao_a_mesma_linha(self) -> None:
        decisao = tenant_gate("onboarding", "pendente", "registar_entrada")
        self.assertEqual(decisao.regime, "pendente")
        self.assertEqual(decisao.origem, "ambos")
        self.assertTrue(decisao.permitido)

    def test_as_seis_linhas_celula_a_celula(self) -> None:
        for regime in REGIMES:
            for accao in ACCOES:
                with self.subTest(regime=regime, accao=accao):
                    self.assertEqual(
                        REGIMES_E_ACCOES[regime][accao], self.ESPERADO[regime][accao]
                    )

    def test_os_exemplos_que_o_criterio_6_nomeia(self) -> None:
        self.assertFalse(
            tenant_gate("restrito", "ativo", "enviar_template_marketing").permitido
        )
        self.assertTrue(tenant_gate("suspenso", "ativo", "mensagem_estatica").permitido)
        self.assertFalse(tenant_gate("suspenso", "ativo", "responder_sessao").permitido)
        self.assertTrue(tenant_gate("encerrado", "ativo", "registar_entrada").permitido)
        for accao in ACCOES:
            if accao == "registar_entrada":
                continue
            with self.subTest(accao=accao):
                self.assertFalse(tenant_gate("encerrado", "ativo", accao).permitido)

    def test_os_trinta_pares_dao_um_regime_conhecido(self) -> None:
        pares = 0
        for t in ESTADOS_DO_TENANT:
            for c in ESTADOS_DO_CANAL:
                self.assertIn(regime_de(t, c), REGIMES)
                pares += 1
        self.assertEqual(pares, 30)

    def test_um_estado_ou_accao_fora_da_lista_levanta(self) -> None:
        maus = (
            ("pausado", "ativo", "registar_entrada"),
            ("ativo", "revogado", "registar_entrada"),
            ("ativo", "ativo", "fazer_tudo"),
            (None, "ativo", "registar_entrada"),
            ("ativo", 7, "registar_entrada"),
            ("ativo", "ativo", 7),
        )
        for args in maus:
            with self.subTest(args=args), self.assertRaises(EstadoDesconhecido):
                tenant_gate(*args)


class TestMetricas(unittest.TestCase):
    """Nenhuma etiqueta leva identificadores (`OBS-I`)."""

    def setUp(self) -> None:
        self.metricas = MetricasDoTen()

    def test_um_tenant_id_nao_passa_a_gramatica(self) -> None:
        self.assertIsNone(ETIQUETA.match(A))
        for metrica in (METRICA_LIMITE_NEGADO, METRICA_ENTITLEMENT_NEGADO):
            with self.subTest(metrica=metrica), self.assertRaises(EtiquetaInvalida):
                self.metricas.contar(metrica, A)

    def test_recusa_etiquetas_mal_formadas_e_metricas_desconhecidas(self) -> None:
        for ma in ("", "A", "1msgs", "msgs-ai", "x" * 64, 7):
            with self.subTest(etiqueta=ma), self.assertRaises(EtiquetaInvalida):
                self.metricas.contar(METRICA_LIMITE_NEGADO, ma)
        with self.assertRaises(EtiquetaInvalida):
            self.metricas.contar("outra_coisa_total", "x")

    def test_conta_soma_e_repoe(self) -> None:
        self.metricas.contar(METRICA_LIMITE_NEGADO, "msgs_ai_mes")
        self.metricas.contar(METRICA_LIMITE_NEGADO, "msgs_ai_mes", 4)
        self.metricas.contar(METRICA_ENTITLEMENT_NEGADO, "vendedor")
        self.assertEqual(
            self.metricas.ler(),
            {
                f"{METRICA_LIMITE_NEGADO}:msgs_ai_mes": 5,
                f"{METRICA_ENTITLEMENT_NEGADO}:vendedor": 1,
            },
        )
        self.metricas.repor()
        self.assertEqual(self.metricas.ler(), {})

    def test_tem_tecto_de_series_por_metrica(self) -> None:
        for i in range(MAXIMO_DE_SERIES):
            self.metricas.contar(METRICA_LIMITE_NEGADO, f"chave_{i}")
        with self.assertRaises(OverflowError):
            self.metricas.contar(METRICA_LIMITE_NEGADO, "mais_uma")
        self.metricas.contar(METRICA_LIMITE_NEGADO, "chave_0")
        self.metricas.contar(METRICA_ENTITLEMENT_NEGADO, "vendedor")

    def test_a_exposicao_mostra_as_duas_a_zero(self) -> None:
        texto = self.metricas.exposicao()
        self.assertIn("# TYPE ten_limit_denied_total counter", texto)
        self.assertIn("\nten_limit_denied_total 0\n", texto)
        self.assertIn("\nten_entitlement_denied_total 0\n", texto)

    def test_a_exposicao_escreve_as_etiquetas_do_criterio_7(self) -> None:
        self.metricas.contar(METRICA_LIMITE_NEGADO, "msgs_ai_mes", 3)
        self.metricas.contar(METRICA_ENTITLEMENT_NEGADO, "vendedor")
        texto = self.metricas.exposicao()
        self.assertIn('ten_limit_denied_total{key="msgs_ai_mes"} 3', texto)
        self.assertIn('ten_entitlement_denied_total{modulo="vendedor"} 1', texto)
        self.assertNotIn(A, texto)


class TestHookDeTool(unittest.TestCase):
    """O passo 2 do pipeline de `invoke` (`docs/tecnica/02` §6.1)."""

    def setUp(self) -> None:
        self.metricas = MetricasDoTen()
        self.ctx = contexto_de(A)

    def test_deixa_passar_quando_permite_e_nao_ha_chave(self) -> None:
        bd = BaseFalsa([linha_de_entitlement()])
        self.assertIsNone(
            hook_de_tool(bd, self.ctx, modulo="vendedor", metricas=self.metricas)
        )
        self.assertEqual(len(bd.chamadas), 1)

    def test_entitlement_denied_e_sem_consumir(self) -> None:
        bd = BaseFalsa([linha_de_entitlement(ativo=False, permitido=False)])
        erro = hook_de_tool(
            bd,
            self.ctx,
            modulo="vendedor",
            chave="msgs_ai_mes",
            idempotency_key="k",
            metricas=self.metricas,
        )
        self.assertEqual(erro, ErroDeTool(codigo=CODIGO_ENTITLEMENT_TOOL, modulo="vendedor"))
        self.assertEqual(len(bd.chamadas), 1)

    def test_limit_exceeded_com_o_tecto(self) -> None:
        bd = BaseFalsa(
            [linha_de_entitlement()],
            [linha_de_consumo(aceite=False, valor=100, limite=100)],
        )
        erro = hook_de_tool(
            bd,
            self.ctx,
            modulo="vendedor",
            chave="msgs_ai_mes",
            idempotency_key="k",
            metricas=self.metricas,
        )
        self.assertEqual(
            erro,
            ErroDeTool(
                codigo=CODIGO_LIMITE, modulo="vendedor", chave="msgs_ai_mes", limite=100
            ),
        )

    def test_limite_nulo_e_entitlement_e_nao_limite(self) -> None:
        bd = BaseFalsa(
            [linha_de_entitlement()],
            [linha_de_consumo(aceite=False, valor=0, limite=None)],
        )
        erro = hook_de_tool(
            bd,
            self.ctx,
            modulo="vendedor",
            chave="marcacoes_mes",
            idempotency_key="k",
            metricas=self.metricas,
        )
        self.assertEqual(erro.codigo, CODIGO_ENTITLEMENT_TOOL)
        self.assertEqual(erro.chave, "marcacoes_mes")

    def test_aceite_devolve_none_e_passa_os_argumentos(self) -> None:
        bd = BaseFalsa([linha_de_entitlement()], [linha_de_consumo()])
        quando = "2026-12-01T00:00:00+01:00"
        self.assertIsNone(
            hook_de_tool(
                bd,
                self.ctx,
                modulo="vendedor",
                chave="msgs_ai_mes",
                quantidade=3,
                idempotency_key="sha256",
                limite=10,
                agora=quando,
                metricas=self.metricas,
            )
        )
        # A chave que vai a base e a **derivada**, e nao a que lhe deram.
        derivada = derivar_chave_de_idempotencia(
            "ten.v1", A, "vendedor", "msgs_ai_mes", "sha256"
        )
        self.assertEqual(
            bd.chamadas[1][1], (A, "msgs_ai_mes", 3, derivada, 10, quando)
        )
        self.assertNotEqual(derivada, "sha256")

    def test_a_chave_do_02_63_e_so_um_componente(self) -> None:
        """C1: a chave de quem chama nao e a chave efectiva.

        A mesma chave do `02` §6.3 em dois modulos, ou em duas chaves de
        limite, deixa de ser a mesma chave de idempotencia: o ambito da
        desduplicacao e do servidor e nao de quem chama.
        """
        vistas = []
        for modulo, chave in (
            ("vendedor", "msgs_ai_mes"),
            ("servicos", "msgs_ai_mes"),
            ("vendedor", "marcacoes_mes"),
        ):
            bd = BaseFalsa([linha_de_entitlement()], [linha_de_consumo()])
            hook_de_tool(
                bd,
                self.ctx,
                modulo=modulo,
                chave=chave,
                idempotency_key="a-mesma-de-sempre",
                metricas=self.metricas,
            )
            efectiva = bd.chamadas[1][1][3]
            self.assertNotEqual(efectiva, "a-mesma-de-sempre")
            self.assertRegex(efectiva, r"^[0-9a-f]{64}$")
            vistas.append(efectiva)
        self.assertEqual(len(set(vistas)), 3)

    def test_o_tecto_por_pedido_corre_antes_do_consumo(self) -> None:
        """M5: um pedido que nao cabe no tecto **nao** gasta o balde.

        Era o defeito medido: com o plano `free`, consumir
        `valor_max_pedido_minor` pela `ten_consumir` gastava num pedido de
        50 000 Kz o tecto inteiro. Aqui o tecto le-se (`SQL_TECTO`), nao
        escreve, e so se consome depois de caber.
        """
        bd = BaseFalsa(
            [linha_de_entitlement()],
            [{"tecto": 5_000_000}],
            [linha_de_consumo()],
        )
        self.assertIsNone(
            hook_de_tool(
                bd,
                self.ctx,
                modulo="vendedor",
                chave="msgs_ai_mes",
                idempotency_key="k",
                tecto_chave="valor_max_pedido_minor",
                tecto_valor=4_000_000,
                metricas=self.metricas,
            )
        )
        self.assertEqual(
            [sql for sql, _ in bd.chamadas],
            [SQL_ENTITLEMENT, SQL_TECTO, SQL_CONSUMIR],
        )

    def test_o_tecto_que_nao_chega_recusa_sem_consumir(self) -> None:
        bd = BaseFalsa([linha_de_entitlement()], [{"tecto": 5_000_000}])
        erro = hook_de_tool(
            bd,
            self.ctx,
            modulo="vendedor",
            chave="msgs_ai_mes",
            idempotency_key="k",
            tecto_chave="valor_max_pedido_minor",
            tecto_valor=6_000_000,
            metricas=self.metricas,
        )
        self.assertEqual(
            erro,
            ErroDeTool(
                codigo=CODIGO_LIMITE,
                modulo="vendedor",
                chave="valor_max_pedido_minor",
                limite=5_000_000,
            ),
        )
        # Duas chamadas: o entitlement e o tecto. **Nenhum consumo.**
        self.assertEqual(len(bd.chamadas), 2)
        self.assertNotIn(SQL_CONSUMIR, [sql for sql, _ in bd.chamadas])

    def test_tecto_sem_entitlement_que_o_declare_e_entitlement_denied(self) -> None:
        bd = BaseFalsa([linha_de_entitlement()], [{"tecto": None}])
        erro = hook_de_tool(
            bd,
            self.ctx,
            modulo="vendedor",
            tecto_chave="manual_max_minor",
            tecto_valor=1,
            metricas=self.metricas,
        )
        self.assertEqual(
            erro,
            ErroDeTool(
                codigo=CODIGO_ENTITLEMENT_TOOL,
                modulo="vendedor",
                chave="manual_max_minor",
            ),
        )

    def test_metade_do_tecto_levanta(self) -> None:
        """A chave sem o valor, ou o valor sem a chave, nao e uma pergunta."""
        for argumentos in (
            {"tecto_chave": "manual_max_minor"},
            {"tecto_valor": 10},
        ):
            with self.subTest(**argumentos), self.assertRaises(QuantidadeInvalida):
                hook_de_tool(
                    BaseFalsa([linha_de_entitlement()]),
                    self.ctx,
                    modulo="vendedor",
                    metricas=self.metricas,
                    **argumentos,
                )

    def test_sem_chave_de_idempotencia_levanta(self) -> None:
        bd = BaseFalsa([linha_de_entitlement()])
        with self.assertRaises(ChaveDeIdempotenciaInvalida):
            hook_de_tool(
                bd, self.ctx, modulo="vendedor", chave="msgs_ai_mes", metricas=self.metricas
            )

    def test_usa_a_cache_que_lhe_derem(self) -> None:
        cache = CacheDeEntitlements()
        bd = BaseFalsa([linha_de_entitlement()], [linha_de_entitlement()])
        hook_de_tool(bd, self.ctx, modulo="vendedor", cache=cache, metricas=self.metricas)
        hook_de_tool(bd, self.ctx, modulo="vendedor", cache=cache, metricas=self.metricas)
        self.assertEqual(len(bd.chamadas), 1)

    def test_o_tenant_vem_do_contexto_e_nao_de_argumentos(self) -> None:
        bd = BaseFalsa([linha_de_entitlement()], [linha_de_consumo()])
        hook_de_tool(
            bd,
            contexto_de(A),
            modulo="vendedor",
            chave="msgs_ai_mes",
            idempotency_key="k",
            metricas=self.metricas,
        )
        for _, parametros in bd.chamadas:
            self.assertEqual(parametros[0], A)
            self.assertNotIn(B, [str(p) for p in parametros])

    def test_o_hook_nao_le_args_nenhuns(self) -> None:
        """A assinatura nao tem `args`, e a fonte nao os menciona.

        «O modelo nunca ve nem fornece `tenant_id`» (`02` §6.1): a forma de o
        garantir e nao haver por onde.
        """
        fonte = (
            RAIZ / "libs" / "py-core" / "src" / "kamba_core" / "ten" / "hook.py"
        ).read_text(encoding="utf-8")
        codigo = "\n".join(
            linha for linha in fonte.splitlines() if not linha.lstrip().startswith("#")
        )
        # O unico `args` do ficheiro esta nas docstrings, a dizer que nao se
        # leem. Nenhuma linha de codigo o usa como nome.
        self.assertNotIn("args[", codigo)
        self.assertNotIn("args.get", codigo)
        self.assertNotIn("args:", codigo.split('"""')[-1])


class TestNaoRegistaNada(unittest.TestCase):
    """Nenhum caminho escreve em *log*, e nenhum modulo importa controlador."""

    MODULOS = ("consultas", "entitlements", "estados", "hook", "metricas")

    def test_nenhum_caminho_escreve_em_log(self) -> None:
        bd = BaseFalsa(
            [linha_de_entitlement(ativo=False, permitido=False)],
            [linha_de_consumo(aceite=False, valor=1, limite=1)],
        )
        metricas = MetricasDoTen()
        with self.assertLogs(level=logging.DEBUG) as apanhado:
            logging.getLogger("sentinela").debug("so para o assertLogs ter uma linha")
            check_entitlement(bd, A, "vendedor", metricas=metricas)
            consume_limit(bd, A, "msgs_ai_mes", 1, "k", metricas=metricas)
            tenant_gate("ativo", "ativo", "registar_entrada")
        self.assertEqual(len(apanhado.output), 1)

    def test_nenhum_modulo_importa_controlador_nem_imprime(self) -> None:
        base = RAIZ / "libs" / "py-core" / "src" / "kamba_core" / "ten"
        for nome in self.MODULOS:
            with self.subTest(modulo=nome):
                fonte = (base / f"{nome}.py").read_text(encoding="utf-8")
                for proibido in ("import psycopg", "import pg8000", "import asyncpg"):
                    self.assertNotIn(proibido, fonte)
                self.assertNotIn("print(", fonte)
                self.assertNotIn("import logging", fonte)

    def test_o_pyproject_continua_sem_dependencias(self) -> None:
        texto = (RAIZ / "libs" / "py-core" / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("dependencies = []", texto)


class TestParidadeDoTypeScript(unittest.TestCase):
    """O mesmo SQL, a mesma matriz e os mesmos numeros dos dois lados.

    O padrao e o do KAM-005 (`TestParidadeDoGuardaDePii`) e o do KAM-006
    (`TestParidadeDoTypeScript` de `test_eventos_consumo.py`): duas
    implementacoes do mesmo contrato so se mantem honestas se houver uma
    maquina a confronta-las.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.consultas = CONSULTAS_TS.read_text(encoding="utf-8")
        cls.estados = ESTADOS_TS.read_text(encoding="utf-8")
        cls.metricas = METRICAS_TS.read_text(encoding="utf-8")
        cls.entitlements = ENTITLEMENTS_TS.read_text(encoding="utf-8")
        cls.middleware = MIDDLEWARE_TS.read_text(encoding="utf-8")

    def _sql_do_typescript(self, nome: str) -> str:
        achado = re.search(rf"export const {nome} = `(.*?)`;", self.consultas, re.S)
        self.assertIsNotNone(achado, f"nao se encontrou {nome} em {CONSULTAS_TS.name}")
        # O marcador e a unica diferenca: `%s` e o que a DB-API le. A posicao e
        # o significado de cada parametro nao mudam.
        return re.sub(r"\$\d+", "%s", achado.group(1))

    def _const_do_typescript(self, fonte: str, nome: str) -> str:
        achado = re.search(rf'export const {nome} = "([^"]*)";', fonte)
        self.assertIsNotNone(achado, nome)
        return achado.group(1)

    def _numero_do_typescript(self, fonte: str, nome: str) -> int:
        achado = re.search(rf"export const {nome} = ([0-9_]+);", fonte)
        self.assertIsNotNone(achado, nome)
        return int(achado.group(1).replace("_", ""))

    def test_os_ficheiros_do_typescript_existem(self) -> None:
        for ficheiro in (
            CONSULTAS_TS,
            ESTADOS_TS,
            METRICAS_TS,
            ENTITLEMENTS_TS,
            MIDDLEWARE_TS,
            REVISAO,
        ):
            with self.subTest(ficheiro=ficheiro.name):
                self.assertTrue(ficheiro.is_file(), ficheiro)

    def test_o_sql_e_o_mesmo_caracter_a_caracter(self) -> None:
        for nome, nosso in (
            ("SQL_PERIODO", SQL_PERIODO),
            ("SQL_ENTITLEMENT", SQL_ENTITLEMENT),
            ("SQL_CONSUMIR", SQL_CONSUMIR),
            ("SQL_TECTO", SQL_TECTO),
        ):
            with self.subTest(sql=nome):
                self.assertEqual(self._sql_do_typescript(nome), nosso)

    def test_o_sql_chama_as_funcoes_da_revisao_0007(self) -> None:
        """E as funcoes existem mesmo na revisao, com a assinatura certa."""
        revisao = REVISAO.read_text(encoding="utf-8")
        self.assertIn("CREATE FUNCTION platform.ten_periodo(", revisao)
        self.assertIn("CREATE FUNCTION platform.ten_consumir(", revisao)
        self.assertIn("platform.ten_periodo(coalesce(%s, now()))", SQL_PERIODO)
        self.assertIn(
            "platform.ten_consumir(%s, %s, %s, %s, %s, coalesce(%s, now()))",
            SQL_CONSUMIR,
        )

    def test_os_dois_coalesce_existem_e_pela_mesma_razao(self) -> None:
        """O `SQL_PERIODO` tinha-o a menos, e os dois lados divergiam nisso.

        Medido pela revisao adversarial: sem instante, o `SQL_PERIODO`
        mandava `NULL` a funcao, o Python devolvia `None` em silencio e o
        TypeScript levantava. Um argumento nomeado ausente nao se exprime
        numa chamada posicional — a razao e a mesma nas duas consultas, e
        agora o `coalesce` tambem.
        """
        for nome, sql in (("SQL_PERIODO", SQL_PERIODO), ("SQL_CONSUMIR", SQL_CONSUMIR)):
            with self.subTest(sql=nome):
                self.assertIn("coalesce(%s, now())", sql)
        # E a razao esta escrita nos dois ficheiros, nao so num.
        for fonte in (
            self.consultas,
            (
                RAIZ / "libs" / "py-core" / "src" / "kamba_core" / "ten" / "consultas.py"
            ).read_text(encoding="utf-8"),
        ):
            self.assertIn("posicional", fonte)

    def test_o_sql_do_tecto_e_so_uma_chamada(self) -> None:
        """A regra do tecto **nao** esta aqui: esta na `platform.ten_tecto`.

        A primeira versao desta constante trazia o `min((limites ->>
        chave)::bigint)` para a biblioteca, e era a unica consulta do ficheiro
        a infringir o argumento da docstring — duas copias da mesma regra, e a
        segunda a divergir no dia em que a primeira mudasse. Hoje a regra e
        uma funcao da revisao, que a `ten_consumir` tambem chama.
        """
        self.assertIn("platform.ten_tecto(%s, %s)", SQL_TECTO)
        # Nem o minimo, nem a tabela, nem o filtro: nada disso e desta
        # biblioteca.
        for fora in ("min(", "limites", "platform.entitlements", "ativo"):
            with self.subTest(fora=fora):
                self.assertNotIn(fora, SQL_TECTO)
        # E nao escreve: nem `INSERT`, nem `UPDATE`, nem `ten_consumir`.
        for proibido in ("INSERT", "UPDATE", "DELETE", "ten_consumir", "tenant_usage"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, SQL_TECTO)

    def test_a_funcao_do_tecto_existe_na_revisao(self) -> None:
        """A `ten_tecto` tem de estar na `0007`, como as outras duas.

        **Este teste arma-se sozinho.** A funcao nasce na metade da revisao
        desta mesma correccao; enquanto o ramo nao a tiver, salta com a razao
        escrita, e passa a correr a serio no instante em que as duas metades
        se juntarem. Um `skip` que diz o que falta e preferivel a uma
        asserciao que falha por uma razao que nao e um defeito.
        """
        revisao = REVISAO.read_text(encoding="utf-8")
        if "ten_tecto" not in revisao:
            self.skipTest(
                "a `platform.ten_tecto` ainda nao esta na revisao `0007` deste "
                "ramo: vem na metade da revisao. O `SQL_TECTO` ja a chama, e "
                "este teste confronta-a assim que ela chegar."
            )
        self.assertIn("CREATE FUNCTION platform.ten_tecto(", revisao)
        # E a `ten_consumir` passou a chama-la, que e o que faz da regra uma
        # so. Se alguem voltar a escrever o `min` dentro da `ten_consumir`,
        # ha outra vez duas copias e isto cai.
        self.assertIn("platform.ten_tecto(p_tenant, p_chave)", revisao)
        self.assertNotIn("min((e.limites ->> p_chave)::bigint)", revisao)

    @staticmethod
    def _so_codigo_py(fonte: str) -> str:
        """A fonte sem docstrings nem comentarios.

        As docstrings deste pacote **falam** de `date_trunc` e de
        `Africa/Luanda` para dizer que nao estao la; procurar as palavras no
        ficheiro inteiro apanhava a explicacao em vez do defeito.
        """
        sem_docstrings = re.sub(r'"""[\s\S]*?"""', "", fonte)
        return "\n".join(
            linha
            for linha in sem_docstrings.splitlines()
            if not linha.lstrip().startswith("#")
        )

    @staticmethod
    def _so_codigo_ts(fonte: str) -> str:
        sem_blocos = re.sub(r"/\*[\s\S]*?\*/", "", fonte)
        return re.sub(r"//.*$", "", sem_blocos, flags=re.M)

    def test_nenhum_dos_lados_reescreve_a_aritmetica(self) -> None:
        """Nem o fuso, nem o `date_trunc`, nem a soma do contador.

        As quatro fontes passam primeiro por um despir de comentarios: o que
        se procura e codigo que reescreva a regra, e nao prosa que explique
        que ela vive na `0007`.
        """
        fontes = {
            "py/consultas": (
                RAIZ / "libs" / "py-core" / "src" / "kamba_core" / "ten" / "consultas.py"
            ).read_text(encoding="utf-8"),
            "py/entitlements": (
                RAIZ
                / "libs"
                / "py-core"
                / "src"
                / "kamba_core"
                / "ten"
                / "entitlements.py"
            ).read_text(encoding="utf-8"),
            "ts/consultas": self.consultas,
            "ts/entitlements": self.entitlements,
        }
        for nome, fonte in fontes.items():
            despir = self._so_codigo_py if nome.startswith("py/") else self._so_codigo_ts
            codigo = despir(fonte)
            with self.subTest(fonte=nome):
                self.assertNotIn("date_trunc", codigo)
                self.assertNotIn("Africa/Luanda", codigo)
                self.assertNotIn("ZoneInfo", codigo)
                self.assertNotIn("toLocaleString", codigo)
                # E o SQL — que nao e comentario — tambem nao a reescreve.
                for sql in (SQL_PERIODO, SQL_ENTITLEMENT, SQL_CONSUMIR):
                    self.assertNotIn("date_trunc", sql)
                    self.assertNotIn("Africa/Luanda", sql)

    def test_os_estados_e_as_accoes_sao_os_mesmos(self) -> None:
        for nome, nosso in (
            ("ESTADOS_DO_TENANT", ESTADOS_DO_TENANT),
            ("ESTADOS_DO_CANAL", ESTADOS_DO_CANAL),
            ("REGIMES", REGIMES),
            ("ACCOES", ACCOES),
        ):
            with self.subTest(lista=nome):
                achado = re.search(
                    rf"export const {nome} = \[(.*?)\] as const;", self.estados, re.S
                )
                self.assertIsNotNone(achado, nome)
                do_ts = tuple(re.findall(r'"([a-z_]+)"', achado.group(1)))
                self.assertEqual(do_ts, nosso)

    def test_a_ordem_de_precedencia_e_a_mesma_dos_dois_lados(self) -> None:
        """E a ordem de `REGIMES` que **e** a regra: trocar duas linhas muda-a."""
        achado = re.search(
            r"export const REGIMES = \[(.*?)\] as const;", self.estados, re.S
        )
        self.assertIsNotNone(achado)
        self.assertEqual(tuple(re.findall(r'"([a-z_]+)"', achado.group(1))), REGIMES)

    def test_os_mapas_de_regime_sao_os_mesmos(self) -> None:
        for nome, nosso in (
            ("REGIME_DO_TENANT", REGIME_DO_TENANT),
            ("REGIME_DO_CANAL", REGIME_DO_CANAL),
        ):
            with self.subTest(mapa=nome):
                achado = re.search(
                    rf"export const {nome}: [^=]+= \{{(.*?)^\}};",
                    self.estados,
                    re.S | re.M,
                )
                self.assertIsNotNone(achado, nome)
                do_ts = dict(
                    re.findall(r"(\w+): \"([a-z_]+)\",", achado.group(1))
                )
                self.assertEqual(do_ts, nosso)

    def test_a_matriz_e_a_mesma_celula_a_celula(self) -> None:
        corpo = re.search(
            r"export const REGIMES_E_ACCOES: [^=]+= \{(.*?)^\};",
            self.estados,
            re.S | re.M,
        )
        self.assertIsNotNone(corpo)
        for regime in REGIMES:
            bloco = re.search(
                rf"^  {regime}: \{{(.*?)^  \}},", corpo.group(1), re.S | re.M
            )
            self.assertIsNotNone(bloco, regime)
            do_ts = {
                accao: valor == "true"
                for accao, valor in re.findall(
                    r"^    (\w+): (true|false),", bloco.group(1), re.M
                )
            }
            with self.subTest(regime=regime):
                self.assertEqual(do_ts, REGIMES_E_ACCOES[regime])

    def test_os_nomes_das_metricas_sao_os_mesmos(self) -> None:
        self.assertEqual(
            self._const_do_typescript(self.metricas, "METRICA_LIMITE_NEGADO"),
            METRICA_LIMITE_NEGADO,
        )
        self.assertEqual(
            self._const_do_typescript(self.metricas, "METRICA_ENTITLEMENT_NEGADO"),
            METRICA_ENTITLEMENT_NEGADO,
        )
        # E sao os do criterio 7, por extenso, nao derivados de nada.
        self.assertEqual(METRICA_LIMITE_NEGADO, "ten_limit_denied_total")
        self.assertEqual(METRICA_ENTITLEMENT_NEGADO, "ten_entitlement_denied_total")

    def test_a_gramatica_de_etiqueta_e_o_tecto_sao_os_mesmos(self) -> None:
        achado = re.search(r"export const ETIQUETA = /(.+?)/;", self.metricas)
        self.assertIsNotNone(achado)
        self.assertEqual(achado.group(1), ETIQUETA.pattern)
        self.assertEqual(
            self._numero_do_typescript(self.metricas, "MAXIMO_DE_SERIES"),
            MAXIMO_DE_SERIES,
        )

    def test_as_etiquetas_expostas_tem_o_nome_do_criterio_7(self) -> None:
        """`{key}` e `{modulo}`, e nao `{chave}` — o criterio escreve-os assim."""
        self.assertIn('[METRICA_LIMITE_NEGADO]: "key"', self.metricas)
        self.assertIn('[METRICA_ENTITLEMENT_NEGADO]: "modulo"', self.metricas)
        nosso = MetricasDoTen()
        nosso.contar(METRICA_LIMITE_NEGADO, "msgs_ai_mes")
        nosso.contar(METRICA_ENTITLEMENT_NEGADO, "vendedor")
        texto = nosso.exposicao()
        self.assertIn('{key="msgs_ai_mes"}', texto)
        self.assertIn('{modulo="vendedor"}', texto)

    def test_os_codigos_e_os_estados_http_sao_os_mesmos(self) -> None:
        self.assertEqual(
            self._const_do_typescript(self.entitlements, "CODIGO_ENTITLEMENT_HTTP"),
            CODIGO_ENTITLEMENT_HTTP,
        )
        self.assertEqual(
            self._const_do_typescript(self.entitlements, "CODIGO_ENTITLEMENT_TOOL"),
            CODIGO_ENTITLEMENT_TOOL,
        )
        self.assertEqual(
            self._const_do_typescript(self.entitlements, "CODIGO_LIMITE"),
            CODIGO_LIMITE,
        )
        self.assertEqual(
            self._numero_do_typescript(self.entitlements, "HTTP_ENTITLEMENT"),
            HTTP_ENTITLEMENT,
        )
        self.assertEqual(
            self._numero_do_typescript(self.entitlements, "HTTP_LIMITE"), HTTP_LIMITE
        )

    def test_os_dois_nomes_do_entitlement_continuam_diferentes(self) -> None:
        """Um e do criterio 2 (proposta), o outro e do `02` §6.5.

        Se alguem os unificar sem decidir, este teste cai — e a decisao esta
        devolvida ao dono do documento, nao tomada aqui.
        """
        self.assertEqual(CODIGO_ENTITLEMENT_HTTP, "ENTITLEMENT_DISABLED")
        self.assertEqual(CODIGO_ENTITLEMENT_TOOL, "ENTITLEMENT_DENIED")
        self.assertNotEqual(CODIGO_ENTITLEMENT_HTTP, CODIGO_ENTITLEMENT_TOOL)

    def test_o_ttl_o_maximo_e_a_gramatica_de_nome_sao_os_mesmos(self) -> None:
        self.assertEqual(
            self._numero_do_typescript(self.entitlements, "TTL_POR_OMISSAO_MS"),
            TTL_POR_OMISSAO_MS,
        )
        self.assertEqual(
            self._numero_do_typescript(self.entitlements, "MAXIMO_DE_ENTRADAS"),
            MAXIMO_DE_ENTRADAS,
        )
        achado = re.search(r"export const NOME_CANONICO = /(.+?)/;", self.entitlements)
        self.assertIsNotNone(achado)
        self.assertEqual(achado.group(1), NOME_CANONICO.pattern)

    def test_o_ttl_satisfaz_o_criterio_6(self) -> None:
        """«Visivel em <= 60 s». O TTL **e** o limite superior do atraso."""
        self.assertLessEqual(TTL_POR_OMISSAO_MS, 60_000)

    def test_os_dois_lados_dizem_que_nao_ha_evento_de_entitlement(self) -> None:
        """A visibilidade e so por TTL, e isso tem de estar escrito nos dois."""
        for fonte in (
            self.entitlements,
            (
                RAIZ
                / "libs"
                / "py-core"
                / "src"
                / "kamba_core"
                / "ten"
                / "entitlements.py"
            ).read_text(encoding="utf-8"),
        ):
            self.assertIn("`entitlement.updated`", fonte)
            self.assertIn("TTL", fonte)

    def test_a_ordem_do_middleware_e_a_do_hook(self) -> None:
        """Entitlement, depois tecto, depois consumo: nos dois lados.

        Consumir primeiro gastava o tecto de quem nem sequer podia entrar, e
        consumir antes de verificar o tecto por pedido gastava o balde do mes
        a descobrir que o pedido nunca ia passar.
        """
        hook = (
            RAIZ / "libs" / "py-core" / "src" / "kamba_core" / "ten" / "hook.py"
        ).read_text(encoding="utf-8")
        for nome, fonte, chamadas in (
            ("ts", self.middleware, ("checkEntitlement(", "checkCeiling(", "consumeLimit(")),
            ("py", hook, ("check_entitlement(", "check_ceiling(", "consume_limit(")),
        ):
            with self.subTest(lado=nome):
                codigo = fonte.split('"""')[-1] if nome == "py" else fonte
                posicoes = [codigo.index(chamada) for chamada in chamadas]
                self.assertEqual(posicoes, sorted(posicoes), chamadas)

    def test_a_tabela_de_chaves_e_a_mesma_dos_dois_lados(self) -> None:
        """A especie de cada chave, confrontada caracter a caracter.

        Do lado Python e do lado TypeScript a tabela e escrita por extenso, e
        cada uma e confrontada com o registo pelo seu teste. Esta e a terceira
        aresta do triangulo: as duas tabelas tambem tem de ser a mesma.
        """
        corpo = re.search(
            r"export const CHAVES_DE_LIMITE: [^=]+= \{(.*?)^\};",
            self.entitlements,
            re.S | re.M,
        )
        self.assertIsNotNone(corpo)
        do_ts = {
            nome: (categoria, consumivel == "true")
            for nome, categoria, consumivel in re.findall(
                r"nome: \"(\w+)\",\s*categoria: CATEGORIA_(\w+),\s*consumivel: (true|false)",
                corpo.group(1),
            )
        }
        nosso = {
            chave.nome: (chave.categoria.upper(), chave.consumivel)
            for chave in CHAVES_DE_LIMITE.values()
        }
        # Do lado TypeScript a categoria e a **constante**, e e assim que se
        # apanha um valor literal escrito a mao num dos lados.
        self.assertEqual(
            {nome: (categoria, consumivel) for nome, (categoria, consumivel) in do_ts.items()},
            {
                nome: (categoria.replace("CONTADOR_POR_PERIODO", "CONTADOR"), consumivel)
                for nome, (categoria, consumivel) in nosso.items()
            },
        )

    def test_as_tres_categorias_tem_o_mesmo_valor_dos_dois_lados(self) -> None:
        for nome, nosso in (
            ("CATEGORIA_CONTADOR", CATEGORIA_CONTADOR),
            ("CATEGORIA_TECTO_POR_PEDIDO", CATEGORIA_TECTO_POR_PEDIDO),
            ("CATEGORIA_TECTO_POR_JANELA", CATEGORIA_TECTO_POR_JANELA),
        ):
            with self.subTest(categoria=nome):
                self.assertEqual(
                    self._const_do_typescript(self.entitlements, nome), nosso
                )

    def test_o_sqlstate_do_conflito_e_o_mesmo_dos_dois_lados(self) -> None:
        self.assertEqual(
            self._const_do_typescript(
                self.entitlements, "SQLSTATE_CONFLITO_DE_IDEMPOTENCIA"
            ),
            SQLSTATE_CONFLITO_DE_IDEMPOTENCIA,
        )

    def test_o_sqlstate_do_tecto_e_a_marca_sao_os_mesmos(self) -> None:
        """O `22023` e a palavra que o distingue da guarda de `p_agora`.

        Se um dos lados mudar a marca e o outro nao, um deles passa a
        traduzir o que o outro relanca — e o mesmo defeito de dados dava erros
        diferentes consoante a linguagem.
        """
        self.assertEqual(
            self._const_do_typescript(self.entitlements, "SQLSTATE_LIMITE_ILEGIVEL"),
            SQLSTATE_LIMITE_ILEGIVEL,
        )
        self.assertEqual(
            self._const_do_typescript(self.entitlements, "MARCA_DO_TECTO_ILEGIVEL"),
            MARCA_DO_TECTO_ILEGIVEL,
        )
        # E a marca e o nome da funcao da revisao, e nao uma palavra solta: e
        # o que liga esta traducao ao contrato da `0007`.
        self.assertEqual(MARCA_DO_TECTO_ILEGIVEL, "ten_tecto")
        self.assertIn(MARCA_DO_TECTO_ILEGIVEL, SQL_TECTO)

    def test_os_dois_lados_traduzem_os_mesmos_dois_estados(self) -> None:
        """E so esses dois: o resto sobe inalterado, dos dois lados."""
        py = (
            RAIZ / "libs" / "py-core" / "src" / "kamba_core" / "ten" / "entitlements.py"
        ).read_text(encoding="utf-8")
        for nome, fonte in (("ts", self.entitlements), ("py", py)):
            with self.subTest(lado=nome):
                self.assertIn("MARCA_DO_TECTO_ILEGIVEL", fonte)
                self.assertIn("SQLSTATE_LIMITE_ILEGIVEL", fonte)
                self.assertIn("SQLSTATE_CONFLITO_DE_IDEMPOTENCIA", fonte)

    def test_o_estado_http_do_tecto_e_o_mesmo_dos_dois_lados(self) -> None:
        """`403` e nao `429`: um tecto por pedido nao reabre no mes seguinte."""
        self.assertEqual(
            self._numero_do_typescript(self.entitlements, "HTTP_TECTO"), HTTP_TECTO
        )
        self.assertEqual(HTTP_TECTO, 403)
        self.assertNotEqual(HTTP_TECTO, HTTP_LIMITE)

    def test_a_derivacao_tem_os_mesmos_componentes_dos_dois_lados(self) -> None:
        """O mesmo prefixo, a mesma ordem e o mesmo separador.

        O digest nao se pode comparar entre linguagens sem correr as duas; o
        que se compara e a **forma**: os dois ficheiros derivam com
        `ten.v1`, tenant, modulo, chave e a do cliente, por essa ordem, e o
        vector fixo do `TestDerivacaoDaChaveDeIdempotencia` esta escrito
        tambem no teste do TypeScript.
        """
        hook = (
            RAIZ / "libs" / "py-core" / "src" / "kamba_core" / "ten" / "hook.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"ten.v1", normalizar_tenant(tenant), modulo, chave, idempotency_key', hook
        )
        self.assertIn('"ten.v1",', self.middleware)
        for fonte in (self.middleware, hook):
            # A quantidade **nao** entra na derivacao: e a impressao digital
            # do `KA002`, e po-la aqui desarmava-o.
            derivacao = re.search(
                r"deriva\w*ChaveDeIdempotencia\((.*?)\);|derivar_chave_de_idempotencia\((.*?)\)",
                fonte,
                re.S,
            )
            self.assertIsNotNone(derivacao)
            argumentos = derivacao.group(1) or derivacao.group(2)
            self.assertNotIn("quantidade", argumentos)
            self.assertNotIn("quantidade", argumentos.lower())

    def test_o_mesmo_vector_de_derivacao_esta_nos_dois_testes(self) -> None:
        """Um digest igual dos dois lados, sem correr os dois interpretes."""
        teste_ts = (RAIZ / "packages" / "core-ts" / "tests" / "ten.test.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn(TestDerivacaoDaChaveDeIdempotencia.VECTOR, teste_ts)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
