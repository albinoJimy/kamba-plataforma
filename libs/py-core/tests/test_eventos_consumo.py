"""O consumidor idempotente: a transaccao, as tres saidas e a escada (KAM-006).

Sem PostgreSQL: o cliente de base de dados e injectado, e o que se verifica e o
que o consumo faz **a ligacao** — a ordem das instrucoes, os parametros, e o que
nao chega a correr quando desiste. A prova contra um PostgreSQL real (a
deduplicacao sob concorrencia, a RLS, as retencoes) e do gate 8.

    TestDuplicado     `contagem = 0` e `COMMIT`, nao `ROLLBACK`, e nada mais
                      corre — nem a leitura da ordem, nem a maquina, nem o
                      efeito.
    TestAplicado      o efeito corre **antes** do `COMMIT` e com o mesmo
                      cliente; os parametros sao os seis e os quatro, pela ordem.
    TestPreCondicao   a verificacao de estado corre **fora** do `exige_ordem`:
                      um tipo que causa transicao nunca se aplica sem ela.
    TestAdiar         estado inexistente e transicao ainda invalida. `None`
                      nunca e «pode».
    TestForaDeOrdem   seq atrasado **E** transicao invalida. Uma coisa so nao
                      basta — e e nessa diferenca que um pagamento se perde.
    TestRollback      o efeito que falha desfaz a marca; um `ROLLBACK` que
                      tambem falhe nao esconde o erro de cima.
    TestEscada        1, 5, 30, 120, 600 s sobre 1 + 5 tentativas, e o
                      `atraso_ms` que poupa um `* 1000` a quem re-enfileira.
    TestLerSeq        um `seq` que nao e inteiro nao se compara: levanta.
    TestNaoRegistaNada
                      nenhum caminho escreve em *log* nenhum, e o modulo nao
                      importa `psycopg`.
    TestParidadeDoTypeScript
                      a escada, o adiamento, os nomes das metricas e **o SQL**
                      sao os mesmos do `packages/core-ts/src/eventos/`. E o
                      padrao do KAM-005 (`TestParidadeDoGuardaDePii`).
"""

from __future__ import annotations

import logging
import re
import unittest
from pathlib import Path

from kamba_core.eventos import consumo, estados
from kamba_core.eventos.consumo import (
    ADIAMENTO_POR_OMISSAO,
    DESFECHOS_DO_CONSUMO,
    ESCADA_DO_CONSUMIDOR,
    METRICA_CONSUMIDOS,
    METRICA_RETENTATIVAS,
    SQL_MARCAR_CONSUMIDO,
    SQL_ULTIMO_SEQ,
    TENTATIVAS,
    Adiar,
    ForaDeOrdem,
    MaquinaEmFalta,
    OpcoesDoConsumo,
    Resultado,
    atraso_da_tentativa_do_consumidor,
    consumir,
)

RAIZ = Path(__file__).resolve().parents[3]
EVENTOS_TS = RAIZ / "packages" / "core-ts" / "src" / "eventos"
CONSUMO_TS = EVENTOS_TS / "consumo.ts"
CONSULTAS_TS = EVENTOS_TS / "consultas_consumo.ts"
METRICAS_TS = EVENTOS_TS / "metricas.ts"
REVISAO = RAIZ / "db" / "migrations" / "versions" / "0005_consumo_dlq.py"

TENANT = "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4"
EVENTO = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
CONSUMIDOR = "com"

SQL_DO_EFEITO = "UPDATE platform.orders SET estado = %s WHERE id = %s"


def _envelope(tipo: str = "payment.confirmed", seq: int = 7) -> dict[str, object]:
    return {
        "id": EVENTO,
        "tipo": tipo,
        "versao": 1,
        "tenant_id": TENANT,
        "agregado": {"tipo": "order", "id": "ORD-1", "seq": seq},
        "payload": {"order_id": "ORD-1"},
    }


class _Bd:
    """Uma ligacao falsa que guarda o que lhe mandaram, pela ordem.

    `contagem` e o que o `INSERT ... ON CONFLICT` devolve: 1 escreveu, 0 ja
    existia, `None` o cliente nao sabe (o `rowCount` nulo do `pg`).
    """

    def __init__(
        self,
        *,
        contagem: int | None = 1,
        ultimo: object = None,
        sem_linha: bool = False,
        rollback_falha: bool = False,
        falha_na_leitura: bool = False,
    ) -> None:
        self.contagem = contagem
        self.ultimo = ultimo
        self.sem_linha = sem_linha
        self.rollback_falha = rollback_falha
        self.falha_na_leitura = falha_na_leitura
        self.registo: list[tuple[str, tuple[object, ...]]] = []

    def executar(self, sql: str, parametros: tuple[object, ...] = ()) -> Resultado:
        self.registo.append((sql, tuple(parametros)))
        if sql == "ROLLBACK" and self.rollback_falha:
            raise RuntimeError("ligacao perdida")
        if sql == SQL_MARCAR_CONSUMIDO:
            return Resultado(contagem=self.contagem)
        if sql == SQL_ULTIMO_SEQ:
            if self.falha_na_leitura:
                raise RuntimeError("base indisponivel")
            if self.sem_linha:
                return Resultado(linhas=())
            return Resultado(linhas=({"ultimo": self.ultimo},))
        return Resultado(contagem=1)

    def verbos(self) -> list[str]:
        nomes = {
            SQL_MARCAR_CONSUMIDO: "marcar",
            SQL_ULTIMO_SEQ: "ultimo_seq",
            SQL_DO_EFEITO: "efeito",
        }
        return [nomes.get(sql, sql) for sql, _ in self.registo]

    def parametros_de(self, sql: str) -> tuple[object, ...]:
        return next(p for s, p in self.registo if s == sql)


class _Maquina:
    def __init__(self, estado: str | None) -> None:
        self.estado = estado
        self.pedidos: list[tuple[str, str]] = []

    def estado_de(self, agregado_tipo: str, agregado_id: str) -> str | None:
        self.pedidos.append((agregado_tipo, agregado_id))
        return self.estado


class _Metricas:
    def __init__(self) -> None:
        self.contagens: list[tuple[str, str | None, int]] = []

    def contar(self, metrica: str, sufixo: str | None = None, quanto: int = 1) -> None:
        self.contagens.append((metrica, sufixo, quanto))


class _Efeito:
    """Um efeito que escreve na mesma ligacao, e que pode falhar."""

    def __init__(self, erro: BaseException | None = None) -> None:
        self.erro = erro
        self.chamadas = 0
        self.clientes: list[object] = []

    def __call__(self, bd) -> None:
        self.chamadas += 1
        self.clientes.append(bd)
        if self.erro is not None:
            raise self.erro
        bd.executar(SQL_DO_EFEITO, ("paga", "ORD-1"))


def _opcoes(bd: _Bd, **extra) -> OpcoesDoConsumo:
    """As opcoes de um consumo, com uma maquina que diz «pode» por omissao.

    O tipo por omissao (`payment.confirmed`) **causa** a transicao, e desde que
    a pre-condicao saiu de dentro do `exige_ordem` a maquina deixou de ser
    opcional para ele — com ordem ou sem ela. Quem testa a falta dela passa
    `maquina=None` de proposito.
    """
    argumentos: dict[str, object] = {
        "bd": bd,
        "consumer": CONSUMIDOR,
        "envelope": _envelope(),
        "maquina": _Maquina("aguarda_pagamento"),
    }
    argumentos.update(extra)
    return OpcoesDoConsumo(**argumentos)  # type: ignore[arg-type]


class TestDuplicado(unittest.TestCase):
    def test_zero_linhas_e_duplicado_e_confirma(self) -> None:
        bd = _Bd(contagem=0)
        efeito = _Efeito()
        metricas = _Metricas()
        resultado = consumir(_opcoes(bd, metricas=metricas), efeito)
        self.assertEqual(resultado.desfecho, "duplicado")
        self.assertIsNone(resultado.ultimo_seq)
        self.assertEqual(bd.verbos(), ["BEGIN", "marcar", "COMMIT"])
        self.assertEqual(efeito.chamadas, 0)
        self.assertEqual(metricas.contagens, [(METRICA_CONSUMIDOS, "duplicado", 1)])

    def test_nao_e_rollback(self) -> None:
        """Nao ha nada para desfazer, e um `ROLLBACK` lia-se como erro."""
        bd = _Bd(contagem=0)
        consumir(_opcoes(bd), _Efeito())
        self.assertNotIn("ROLLBACK", bd.verbos())

    def test_um_duplicado_nao_le_a_ordem_nem_a_maquina(self) -> None:
        bd = _Bd(contagem=0)
        maquina = _Maquina("criada")
        resultado = consumir(
            _opcoes(bd, exige_ordem=True, maquina=maquina), _Efeito()
        )
        self.assertEqual(resultado.desfecho, "duplicado")
        self.assertNotIn("ultimo_seq", bd.verbos())
        self.assertEqual(maquina.pedidos, [])

    def test_contagem_desconhecida_conta_como_zero(self) -> None:
        bd = _Bd(contagem=None)
        self.assertEqual(consumir(_opcoes(bd), _Efeito()).desfecho, "duplicado")


class TestAplicado(unittest.TestCase):
    def test_o_efeito_corre_antes_do_commit_e_com_o_mesmo_cliente(self) -> None:
        bd = _Bd()
        efeito = _Efeito()
        resultado = consumir(_opcoes(bd), efeito)
        self.assertEqual(resultado.desfecho, "aplicado")
        self.assertEqual(bd.verbos(), ["BEGIN", "marcar", "efeito", "COMMIT"])
        self.assertEqual(efeito.clientes, [bd])

    def test_sem_ordem_nao_se_le_o_ultimo_seq(self) -> None:
        bd = _Bd()
        resultado = consumir(_opcoes(bd, exige_ordem=False), _Efeito())
        self.assertNotIn("ultimo_seq", bd.verbos())
        self.assertIsNone(resultado.ultimo_seq)

    def test_os_seis_parametros_da_marca_pela_ordem_do_ddl(self) -> None:
        bd = _Bd()
        consumir(_opcoes(bd), _Efeito())
        self.assertEqual(
            bd.parametros_de(SQL_MARCAR_CONSUMIDO),
            (CONSUMIDOR, EVENTO, TENANT, "order", "ORD-1", 7),
        )

    def test_os_quatro_parametros_da_leitura_da_ordem(self) -> None:
        bd = _Bd(ultimo=5)
        consumir(
            _opcoes(bd, exige_ordem=True, maquina=_Maquina("aguarda_pagamento")),
            _Efeito(),
        )
        self.assertEqual(
            bd.parametros_de(SQL_ULTIMO_SEQ),
            (CONSUMIDOR, "order", "ORD-1", EVENTO),
        )

    def test_com_ordem_e_transicao_valida_aplica_e_devolve_o_ultimo_seq(self) -> None:
        bd = _Bd(ultimo=5)
        maquina = _Maquina("aguarda_pagamento")
        metricas = _Metricas()
        resultado = consumir(
            _opcoes(bd, exige_ordem=True, maquina=maquina, metricas=metricas),
            _Efeito(),
        )
        self.assertEqual(resultado.desfecho, "aplicado")
        self.assertEqual(resultado.ultimo_seq, 5)
        self.assertEqual(maquina.pedidos, [("order", "ORD-1")])
        self.assertEqual(
            bd.verbos(), ["BEGIN", "marcar", "ultimo_seq", "efeito", "COMMIT"]
        )
        self.assertEqual(metricas.contagens, [(METRICA_CONSUMIDOS, "aplicado", 1)])

    def test_o_bigint_vem_como_texto_e_le_se_como_inteiro(self) -> None:
        bd = _Bd(ultimo="5")
        resultado = consumir(
            _opcoes(bd, exige_ordem=True, maquina=_Maquina("aguarda_pagamento")),
            _Efeito(),
        )
        self.assertEqual(resultado.ultimo_seq, 5)

    def test_primeiro_evento_do_agregado_nao_tem_ultimo_seq(self) -> None:
        for bd in (_Bd(ultimo=None), _Bd(sem_linha=True)):
            with self.subTest(linhas=bool(not bd.sem_linha)):
                resultado = consumir(
                    _opcoes(
                        bd, exige_ordem=True, maquina=_Maquina("aguarda_pagamento")
                    ),
                    _Efeito(),
                )
                self.assertIsNone(resultado.ultimo_seq)
                self.assertEqual(resultado.desfecho, "aplicado")

    def test_um_tipo_que_nao_causa_transicao_le_a_ordem_e_nada_mais(self) -> None:
        """Nao e «pode tudo»: e «isto nao e uma transicao de encomenda»."""
        bd = _Bd(ultimo=99)
        maquina = _Maquina("criada")
        resultado = consumir(
            _opcoes(
                bd,
                envelope=_envelope("order.created", seq=1),
                exige_ordem=True,
                maquina=maquina,
            ),
            _Efeito(),
        )
        self.assertEqual(resultado.desfecho, "aplicado")
        self.assertEqual(resultado.ultimo_seq, 99)
        self.assertIn("ultimo_seq", bd.verbos())
        self.assertEqual(maquina.pedidos, [])

    def test_sem_metricas_nao_rebenta(self) -> None:
        self.assertEqual(consumir(_opcoes(_Bd()), _Efeito()).desfecho, "aplicado")


class TestAdiar(unittest.TestCase):
    def test_agregado_que_ainda_nao_existe_adia(self) -> None:
        """`None` nunca e «pode»: e cedo, nao e invalido."""
        bd = _Bd(ultimo=5)
        efeito = _Efeito()
        metricas = _Metricas()
        with self.assertRaises(Adiar) as capturado:
            consumir(
                _opcoes(
                    bd, exige_ordem=True, maquina=_Maquina(None), metricas=metricas
                ),
                efeito,
            )
        self.assertEqual(capturado.exception.segundos, ADIAMENTO_POR_OMISSAO)
        self.assertIn("ainda nao existe", capturado.exception.porque)
        self.assertEqual(efeito.chamadas, 0)
        self.assertEqual(bd.verbos()[-1], "ROLLBACK")
        self.assertNotIn("COMMIT", bd.verbos())
        self.assertEqual(metricas.contagens, [(METRICA_RETENTATIVAS, "adiado", 1)])

    def test_transicao_ainda_invalida_e_em_dia_adia(self) -> None:
        """`criada -> paga` com o seq em dia: a pre-condicao pode ainda chegar."""
        bd = _Bd(ultimo=5)
        with self.assertRaises(Adiar) as capturado:
            consumir(
                _opcoes(
                    bd,
                    envelope=_envelope(seq=9),
                    exige_ordem=True,
                    maquina=_Maquina("criada"),
                ),
                _Efeito(),
            )
        self.assertIn("criada -> paga ainda nao e valido", str(capturado.exception))
        self.assertNotIn("COMMIT", bd.verbos())

    def test_transicao_invalida_sem_ultimo_seq_adia(self) -> None:
        bd = _Bd(ultimo=None)
        with self.assertRaises(Adiar):
            consumir(
                _opcoes(bd, exige_ordem=True, maquina=_Maquina("criada")), _Efeito()
            )

    def test_o_seq_igual_ao_ultimo_nao_e_atrasado(self) -> None:
        """O documento diz `seq < ultima`. Igual nao e atrasado: adia-se."""
        bd = _Bd(ultimo=7)
        with self.assertRaises(Adiar):
            consumir(
                _opcoes(
                    bd,
                    envelope=_envelope(seq=7),
                    exige_ordem=True,
                    maquina=_Maquina("criada"),
                ),
                _Efeito(),
            )

    def test_os_valores_por_omissao_de_adiar(self) -> None:
        adiamento = Adiar()
        self.assertEqual(adiamento.segundos, 5)
        self.assertEqual(str(adiamento), "adiar 5s: pre-condicao de estado por verificar")


class TestForaDeOrdem(unittest.TestCase):
    def test_atrasado_e_invalido_vai_para_a_dlq(self) -> None:
        bd = _Bd(ultimo=12)
        efeito = _Efeito()
        metricas = _Metricas()
        with self.assertRaises(ForaDeOrdem) as capturado:
            consumir(
                _opcoes(
                    bd,
                    envelope=_envelope(seq=7),
                    exige_ordem=True,
                    maquina=_Maquina("criada"),
                    metricas=metricas,
                ),
                efeito,
            )
        erro = capturado.exception
        self.assertEqual(ForaDeOrdem.CODIGO, "fora_de_ordem")
        self.assertTrue(str(erro).startswith("fora_de_ordem: "))
        self.assertIn("seq 7 < 12", erro.detalhe)
        self.assertEqual(efeito.chamadas, 0)
        self.assertEqual(bd.verbos()[-1], "ROLLBACK")
        self.assertNotIn("COMMIT", bd.verbos())
        # Adiar conta como retentativa; `fora_de_ordem` nao se tenta outra vez.
        self.assertEqual(metricas.contagens, [])

    def test_atrasado_com_transicao_valida_aplica_se(self) -> None:
        """Uma coisa so nao basta: o seq atrasado nao e, por si, fora de ordem."""
        bd = _Bd(ultimo=12)
        resultado = consumir(
            _opcoes(
                bd,
                envelope=_envelope(seq=7),
                exige_ordem=True,
                maquina=_Maquina("aguarda_pagamento"),
            ),
            _Efeito(),
        )
        self.assertEqual(resultado.desfecho, "aplicado")
        self.assertEqual(resultado.ultimo_seq, 12)


class TestRollback(unittest.TestCase):
    def test_o_efeito_que_falha_desfaz_a_marca(self) -> None:
        bd = _Bd()
        metricas = _Metricas()
        with self.assertRaises(ZeroDivisionError):
            consumir(_opcoes(bd, metricas=metricas), _Efeito(ZeroDivisionError("x")))
        self.assertEqual(bd.verbos(), ["BEGIN", "marcar", "ROLLBACK"])
        self.assertNotIn("COMMIT", bd.verbos())
        self.assertEqual(metricas.contagens, [])

    def test_um_rollback_que_falha_nao_esconde_o_erro_de_cima(self) -> None:
        bd = _Bd(rollback_falha=True)
        with self.assertRaises(KeyError):
            consumir(_opcoes(bd), _Efeito(KeyError("o erro que interessa")))
        self.assertEqual(bd.verbos(), ["BEGIN", "marcar", "ROLLBACK"])

    def test_uma_leitura_que_falha_tambem_desfaz(self) -> None:
        bd = _Bd(falha_na_leitura=True)
        with self.assertRaises(RuntimeError):
            consumir(
                _opcoes(bd, exige_ordem=True, maquina=_Maquina("aguarda_pagamento")),
                _Efeito(),
            )
        self.assertEqual(bd.verbos(), ["BEGIN", "marcar", "ultimo_seq", "ROLLBACK"])


class TestPreCondicao(unittest.TestCase):
    """A pre-condicao de estado corre **fora** do `exige_ordem`.

    Era o buraco: com ela dentro, uma subscricao de um tipo que causa transicao
    e `exige_ordem = false` aplicava-a sem verificacao nenhuma. A restricao
    `evt_subscricoes_payment_exige_ordem` so obriga ordem em `payment.%`, pelo
    que a configuracao chegava la.
    """

    def test_sem_ordem_a_pre_condicao_continua_a_ser_verificada(self) -> None:
        bd = _Bd()
        efeito = _Efeito()
        with self.assertRaises(Adiar):
            consumir(
                _opcoes(bd, exige_ordem=False, maquina=_Maquina("criada")), efeito
            )
        self.assertEqual(efeito.chamadas, 0)
        self.assertNotIn("COMMIT", bd.verbos())
        # A ordem e outra coisa: sem `exige_ordem` nao se le o ultimo `seq`.
        self.assertNotIn("ultimo_seq", bd.verbos())

    def test_sem_ordem_nunca_ha_fora_de_ordem(self) -> None:
        """Sem o ultimo `seq` nao se sabe se o evento vem atrasado: adia-se."""
        bd = _Bd(ultimo=12)
        with self.assertRaises(Adiar):
            consumir(
                _opcoes(
                    bd,
                    envelope=_envelope(seq=1),
                    exige_ordem=False,
                    maquina=_Maquina("criada"),
                ),
                _Efeito(),
            )

    def test_um_tipo_que_causa_transicao_sem_maquina_e_defeito_de_configuracao(
        self,
    ) -> None:
        for exige_ordem in (True, False):
            with self.subTest(exige_ordem=exige_ordem):
                bd = _Bd(ultimo=5)
                efeito = _Efeito()
                with self.assertRaises(MaquinaEmFalta) as capturado:
                    consumir(
                        _opcoes(bd, exige_ordem=exige_ordem, maquina=None), efeito
                    )
                self.assertIn("ADR-013", str(capturado.exception))
                self.assertEqual(efeito.chamadas, 0)
                self.assertEqual(bd.verbos()[-1], "ROLLBACK")
                self.assertNotIn("COMMIT", bd.verbos())

    def test_um_tipo_que_nao_causa_transicao_nao_precisa_de_maquina(self) -> None:
        for exige_ordem in (True, False):
            with self.subTest(exige_ordem=exige_ordem):
                bd = _Bd(ultimo=3)
                resultado = consumir(
                    _opcoes(
                        bd,
                        envelope=_envelope("channel.connected"),
                        exige_ordem=exige_ordem,
                        maquina=None,
                    ),
                    _Efeito(),
                )
                self.assertEqual(resultado.desfecho, "aplicado")


class TestEscada(unittest.TestCase):
    def test_a_escada_e_a_do_paragrafo_6_4_em_milissegundos(self) -> None:
        self.assertEqual(ESCADA_DO_CONSUMIDOR, (1_000, 5_000, 30_000, 120_000, 600_000))

    def test_tem_uma_entrada_por_retentativa(self) -> None:
        self.assertEqual(TENTATIVAS, 6)
        self.assertEqual(TENTATIVAS, 1 + len(ESCADA_DO_CONSUMIDOR))

    def test_cada_degrau_e_o_da_sua_tentativa(self) -> None:
        self.assertEqual(
            [atraso_da_tentativa_do_consumidor(n) for n in range(1, 6)],
            list(ESCADA_DO_CONSUMIDOR),
        )

    def test_acima_da_escada_fica_no_ultimo_degrau(self) -> None:
        """A sexta falha nao espera: vai para a DLQ."""
        for tentativas in (6, 7, 100):
            with self.subTest(tentativas=tentativas):
                self.assertEqual(
                    atraso_da_tentativa_do_consumidor(tentativas), 600_000
                )

    def test_recusa_o_que_nao_e_uma_tentativa(self) -> None:
        for valor in (0, -1, 1.5, True, "1", None):
            with self.subTest(valor=repr(valor)):
                with self.assertRaises(ValueError):
                    atraso_da_tentativa_do_consumidor(valor)

    def test_o_adiamento_e_em_segundos_e_e_o_do_documento(self) -> None:
        self.assertEqual(ADIAMENTO_POR_OMISSAO, 5)

    def test_o_atraso_em_milissegundos_poupa_a_multiplicacao_na_fronteira(self) -> None:
        """Um `* 1000` esquecido transformava 5 s em 5 ms e queimava as seis."""
        self.assertEqual(Adiar().atraso_ms, ADIAMENTO_POR_OMISSAO * 1_000)
        self.assertEqual(Adiar(30).atraso_ms, 30_000)


class TestLerSeq(unittest.TestCase):
    """Um `seq` que nao se leu nao se compara.

    A assimetria com o TypeScript e deliberada: la o `lerSeq` recusa o que passe
    de `Number.MAX_SAFE_INTEGER`, porque um `bigint` acima de 2^53 arredonda em
    silencio num `number`. O `int` do Python e exacto, pelo que aqui nao ha
    tecto — so a recusa do que nao e inteiro.
    """

    def test_sem_linhas_anteriores_e_none(self) -> None:
        self.assertIsNone(consumo._ler_seq(None))

    def test_o_inteiro_e_a_cadeia_do_condutor_dao_o_mesmo(self) -> None:
        self.assertEqual(consumo._ler_seq(7), 7)
        self.assertEqual(consumo._ler_seq("7"), 7)

    def test_acima_de_dois_elevado_a_53_o_python_e_exacto(self) -> None:
        enorme = 2**53 + 1
        self.assertEqual(consumo._ler_seq(enorme), enorme)
        self.assertEqual(consumo._ler_seq(str(enorme)), enorme)

    def test_o_que_nao_e_inteiro_levanta(self) -> None:
        for valor in (7.5, "7.0", "sete", True, b"7", [7], {"ultimo": 7}):
            with self.subTest(valor=repr(valor)):
                with self.assertRaises(ValueError):
                    consumo._ler_seq(valor)

    def test_um_seq_ilegivel_desfaz_a_transaccao(self) -> None:
        bd = _Bd(ultimo="sete")
        with self.assertRaises(ValueError):
            consumir(
                _opcoes(bd, exige_ordem=True, maquina=_Maquina("aguarda_pagamento")),
                _Efeito(),
            )
        self.assertEqual(bd.verbos(), ["BEGIN", "marcar", "ultimo_seq", "ROLLBACK"])


class TestNaoRegistaNada(unittest.TestCase):
    """O envelope passa por aqui; a *allowlist* do logger nao o conhece."""

    def test_nenhum_caminho_escreve_em_log(self) -> None:
        with self.assertNoLogs(level=logging.DEBUG):
            consumir(_opcoes(_Bd(contagem=0)), _Efeito())
            consumir(_opcoes(_Bd()), _Efeito())
            with self.assertRaises(Adiar):
                consumir(
                    _opcoes(_Bd(), exige_ordem=True, maquina=_Maquina(None)),
                    _Efeito(),
                )
            with self.assertRaises(ForaDeOrdem):
                consumir(
                    _opcoes(
                        _Bd(ultimo=12),
                        envelope=_envelope(seq=1),
                        exige_ordem=True,
                        maquina=_Maquina("criada"),
                    ),
                    _Efeito(),
                )
            with self.assertRaises(RuntimeError):
                consumir(_opcoes(_Bd()), _Efeito(RuntimeError("x")))

    def test_o_modulo_nao_importa_psycopg_nem_imprime(self) -> None:
        """O cliente e injectado: e por isso que isto se testa sem PostgreSQL."""
        self.assertFalse(hasattr(consumo, "psycopg"))
        for modulo in (consumo, estados):
            fonte = Path(modulo.__file__).read_text(encoding="utf-8")
            with self.subTest(modulo=modulo.__name__):
                self.assertIsNone(
                    re.search(r"^\s*(?:import|from) psycopg", fonte, re.M),
                    "o modulo importa psycopg",
                )
                self.assertNotIn("print(", fonte)


class TestParidadeDoTypeScript(unittest.TestCase):
    """Os mesmos numeros e o mesmo SQL dos dois lados, lidos como texto.

    O padrao e o do KAM-005 (`TestParidadeDoGuardaDePii` em
    `db/tests/test_eventos_schema.py`): duas implementacoes do mesmo contrato so
    se mantem honestas se houver uma maquina a confronta-las.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.consumo = CONSUMO_TS.read_text(encoding="utf-8")
        cls.consultas = CONSULTAS_TS.read_text(encoding="utf-8")
        cls.metricas = METRICAS_TS.read_text(encoding="utf-8")

    def _sql_do_typescript(self, nome: str) -> str:
        achado = re.search(
            rf"export const {nome} = `(.*?)`;", self.consultas, re.S
        )
        self.assertIsNotNone(achado, f"nao se encontrou {nome} em {CONSULTAS_TS.name}")
        # O marcador e a unica diferenca: `%s` e o que o `psycopg` le. A posicao
        # e o significado de cada parametro nao mudam.
        return re.sub(r"\$\d+", "%s", achado.group(1))

    def test_os_ficheiros_do_typescript_existem(self) -> None:
        for ficheiro in (CONSUMO_TS, CONSULTAS_TS, METRICAS_TS, REVISAO):
            with self.subTest(ficheiro=ficheiro.name):
                self.assertTrue(ficheiro.is_file(), ficheiro)

    def test_a_escada_e_a_mesma(self) -> None:
        achado = re.search(
            r"ESCADA_DO_CONSUMIDOR = \[(.*?)\] as const;", self.consumo, re.S
        )
        self.assertIsNotNone(achado)
        do_ts = tuple(
            int(n.replace("_", "")) for n in re.findall(r"[0-9_]+", achado.group(1))
        )
        self.assertEqual(do_ts, ESCADA_DO_CONSUMIDOR)

    def test_as_tentativas_derivam_da_escada_nos_dois_lados(self) -> None:
        self.assertIn(
            "export const TENTATIVAS = 1 + ESCADA_DO_CONSUMIDOR.length;", self.consumo
        )
        self.assertEqual(TENTATIVAS, 1 + len(ESCADA_DO_CONSUMIDOR))

    def test_o_adiamento_por_omissao_e_o_mesmo(self) -> None:
        achado = re.search(r"ADIAMENTO_POR_OMISSAO = (\d+);", self.consumo)
        self.assertIsNotNone(achado)
        self.assertEqual(int(achado.group(1)), ADIAMENTO_POR_OMISSAO)

    def test_o_codigo_de_fora_de_ordem_e_o_mesmo(self) -> None:
        achado = re.search(r"CODIGO = '([a-z_]+)'", self.consumo)
        self.assertIsNotNone(achado)
        self.assertEqual(achado.group(1), ForaDeOrdem.CODIGO)

    def test_os_nomes_das_metricas_e_os_desfechos_sao_os_mesmos(self) -> None:
        for nome, valor in (
            ("METRICA_CONSUMIDOS", METRICA_CONSUMIDOS),
            ("METRICA_RETENTATIVAS", METRICA_RETENTATIVAS),
        ):
            with self.subTest(nome=nome):
                achado = re.search(rf'{nome} = "([a-z_]+)"', self.metricas)
                self.assertIsNotNone(achado)
                self.assertEqual(achado.group(1), valor)
        achado = re.search(
            r"DESFECHOS_DO_CONSUMO = \[(.*?)\] as const;", self.metricas, re.S
        )
        self.assertIsNotNone(achado)
        self.assertEqual(
            tuple(re.findall(r'"([a-z_]+)"', achado.group(1))), DESFECHOS_DO_CONSUMO
        )

    def test_o_sql_e_o_mesmo_com_os_mesmos_parametros(self) -> None:
        for nome, nosso in (
            ("SQL_MARCAR_CONSUMIDO", SQL_MARCAR_CONSUMIDO),
            ("SQL_ULTIMO_SEQ", SQL_ULTIMO_SEQ),
        ):
            with self.subTest(sql=nome):
                self.assertEqual(self._sql_do_typescript(nome).split(), nosso.split())

    def test_o_alvo_do_conflito_esta_nomeado(self) -> None:
        """Sem alvo, um conflito noutro indice unico lia-se «duplicado»."""
        self.assertIn(
            "ON CONFLICT (consumer, event_id) DO NOTHING", SQL_MARCAR_CONSUMIDO
        )

    def test_a_pre_condicao_de_estado_corre_fora_do_exige_ordem(self) -> None:
        """Estrutural, e de proposito: a indentacao diz de que bloco e a linha.

        Se alguem voltar a por a leitura do `ESTADO_PRETENDIDO` dentro do
        `if (exigeOrdem)`, a linha ganha dois espacos e isto falha — que e o
        unico sitio onde se nota, porque os dois lados continuariam a compilar.
        """
        self.assertRegex(
            self.consumo,
            r"\n    const pretendido = ESTADO_PRETENDIDO\[envelope\.tipo\];\n",
        )

    def test_o_atraso_em_milissegundos_existe_nos_dois_lados(self) -> None:
        self.assertIn("get atrasoMs()", self.consumo)
        self.assertIn("this.segundos * 1_000", self.consumo)
        self.assertEqual(Adiar(3).atraso_ms, 3_000)

    def test_o_typescript_tem_o_tecto_do_inteiro_seguro_e_o_python_nao(self) -> None:
        """A assimetria e declarada: o `int` do Python nao arredonda.

        Se o `lerSeq` do TypeScript perder a guarda, isto falha — e e a unica
        forma de o notar deste lado.
        """
        self.assertIn("Number.isSafeInteger", self.consumo)
        self.assertEqual(consumo._ler_seq(2**53 + 1), 2**53 + 1)

    def test_as_colunas_da_marca_sao_as_do_ddl_da_revisao_0005(self) -> None:
        """Os nomes de coluna vem da revisao, nao da memoria de quem copiou."""
        ddl = REVISAO.read_text(encoding="utf-8")
        criacao = re.search(
            r"CREATE TABLE platform\.events_consumed \((.*?)\n        \)", ddl, re.S
        )
        self.assertIsNotNone(criacao)
        for coluna in (
            "consumer",
            "event_id",
            "tenant_id",
            "agregado_tipo",
            "agregado_id",
            "agregado_seq",
        ):
            with self.subTest(coluna=coluna):
                self.assertRegex(criacao.group(1), rf"\n\s+{coluna}\s")
                self.assertIn(coluna, SQL_MARCAR_CONSUMIDO)

    def test_as_colunas_de_agregado_sao_not_null_na_revisao_0005(self) -> None:
        """O `max()` ignora `NULL`: uma linha sem `seq` fazia o maximo parecer
        mais antigo do que e, e com isso um evento atrasado passava por estar em
        ordem. Por isso e que `_ler_seq(None)` significa «nao ha anterior»."""
        ddl = REVISAO.read_text(encoding="utf-8")
        criacao = re.search(
            r"CREATE TABLE platform\.events_consumed \((.*?)\n        \)", ddl, re.S
        )
        self.assertIsNotNone(criacao)
        for coluna in ("agregado_tipo", "agregado_id", "agregado_seq"):
            with self.subTest(coluna=coluna):
                self.assertRegex(criacao.group(1), rf"\n\s+{coluna}\s+\w+ NOT NULL")


if __name__ == "__main__":
    unittest.main()
