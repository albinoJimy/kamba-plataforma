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

import logging
import re
import unittest
from pathlib import Path

from kamba_core import ten
from kamba_core.ten import (
    ACCOES,
    CODIGO_ENTITLEMENT_HTTP,
    CODIGO_ENTITLEMENT_TOOL,
    CODIGO_LIMITE,
    ESTADOS_DO_CANAL,
    ESTADOS_DO_TENANT,
    ETIQUETA,
    HTTP_ENTITLEMENT,
    HTTP_LIMITE,
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
    TTL_POR_OMISSAO_MS,
    CacheDeEntitlements,
    ChaveDeIdempotenciaInvalida,
    Entitlement,
    ErroDeTool,
    EstadoDesconhecido,
    EtiquetaInvalida,
    MetricasDoTen,
    NomeInvalido,
    QuantidadeInvalida,
    RespostaIlegivel,
    Resultado,
    agora_ms,
    check_entitlement,
    consume_limit,
    exigir_nome,
    hook_de_tool,
    inteiro,
    mais_restritivo,
    periodo,
    regime_de,
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
        bd = BaseFalsa([{"periodo": "2026-12-01"}])
        self.assertEqual(periodo(bd), "2026-12-01")
        self.assertEqual(bd.chamadas[0][1], (None,))

    def test_uma_resposta_sem_periodo_levanta(self) -> None:
        with self.assertRaises(RespostaIlegivel):
            periodo(BaseFalsa([{"outra": 1}]))
        with self.assertRaises(RespostaIlegivel):
            periodo(BaseFalsa([]))


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

    def test_a_ordem_de_precedencia_e_a_proposta(self) -> None:
        self.assertEqual(
            REGIMES,
            ("encerrado", "suspenso", "desligado", "pendente", "restrito", "ativo"),
        )
        self.assertEqual(mais_restritivo("ativo", "encerrado"), "encerrado")
        self.assertEqual(mais_restritivo("encerrado", "ativo"), "encerrado")
        self.assertEqual(mais_restritivo("restrito", "pendente"), "pendente")
        self.assertEqual(mais_restritivo("suspenso", "desligado"), "suspenso")
        self.assertEqual(mais_restritivo("ativo", "ativo"), "ativo")

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
        self.assertEqual(
            bd.chamadas[1][1], (A, "msgs_ai_mes", 3, "sha256", 10, quando)
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
        ):
            with self.subTest(sql=nome):
                self.assertEqual(self._sql_do_typescript(nome), nosso)

    def test_o_sql_chama_as_funcoes_da_revisao_0007(self) -> None:
        """E as funcoes existem mesmo na revisao, com a assinatura certa."""
        revisao = REVISAO.read_text(encoding="utf-8")
        self.assertIn("CREATE FUNCTION platform.ten_periodo(", revisao)
        self.assertIn("CREATE FUNCTION platform.ten_consumir(", revisao)
        self.assertIn("platform.ten_periodo(%s)", SQL_PERIODO)
        self.assertIn(
            "platform.ten_consumir(%s, %s, %s, %s, %s, coalesce(%s, now()))",
            SQL_CONSUMIR,
        )

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
        """Entitlement primeiro, consumo depois: nos dois lados.

        Consumir primeiro gastava o tecto de quem nem sequer podia entrar.
        """
        hook = (
            RAIZ / "libs" / "py-core" / "src" / "kamba_core" / "ten" / "hook.py"
        ).read_text(encoding="utf-8")
        for nome, fonte, chamadas in (
            ("ts", self.middleware, ("checkEntitlement(", "consumeLimit(")),
            ("py", hook, ("check_entitlement(", "consume_limit(")),
        ):
            with self.subTest(lado=nome):
                codigo = fonte.split('"""')[-1] if nome == "py" else fonte
                primeira = codigo.index(chamadas[0])
                segunda = codigo.index(chamadas[1])
                self.assertLess(primeira, segunda)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
