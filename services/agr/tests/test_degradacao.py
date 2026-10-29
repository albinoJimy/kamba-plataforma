"""KAM-037 — o modo determinístico sem LLM e a degradação.

Esta bateria mede os oito critérios do bloco pelo ângulo de cada um, e o que ela
**não** mede diz-se aqui para não parecer esquecimento:

* **o ritmo real do proxy** não se mede: o `kamba-chat` é uma imagem por digest e
  o `allowed_fails: 3`/`cooldown_time: 30` foram confirmados pelo KAM-030 contra
  a versão fixada (`docs/evidencia/KAM-030-litellm.md` §4). Aqui mede-se que o
  **nosso** disjuntor usa esses dois números e não os seus próprios;
* **a janela de 24 h** é do Outbound (KAM-015) e não há código dela no AGR; o que
  esta bateria mede é a metade que lhe toca — um turno degradado não reenvia o
  rascunho de um turno anterior, porque o `draft` é do turno;
* **a carga a sério** — mil turnos com a fila acima do limiar — não corre aqui: o
  `Admissao` deste processo conta turnos em memória e o teste de contrapressão
  mede a **regra** (tecto cheio **e** fila acima do limiar), com os contadores
  postos à mão, que é a mesma escolha do `test_admissao`.

## O que a bateria devolve ao fundador, e não decide

Duas leituras do bloco ficam escritas na secção de verificação e **não** se
resolvem em código:

1. **degradado × concierge.** O KAM-037 foi escrito antes do KAM-114 e nenhum dos
   dois diz o que acontece com os dois em vigor. A leitura implementada é «a
   resposta determinística **também** vai a aprovação», e há ensaio que a mede
   (`TestDegradadoComConcierge`);
2. **a pesquisa de catálogo fica fora do modo**, pela letra do critério 2.

## O LLM *fake* falha nos três modos, e os três são os do critério 1

`TempoEsgotado` (o *timeout* de 20 s do `kamba-chat`), `FornecedorFalhou` com
`estado_http=429` e `OrcamentoEsgotado` (o `BUDGET_EXHAUSTED`). Os três são os
erros tipados do `llm/erros.py` e não excepções inventadas: um duplo que
levantasse `RuntimeError` media que o `except` apanha tudo — e o que o ticket
exige é precisamente que ele **não** apanhe tudo.
"""

from __future__ import annotations

import asyncio
import re
import unittest
from typing import Any

from test_vendedor import Handoff, Relogio, Saida, correr, estado_de, montar

from kamba_agr import degradacao as deg
from kamba_agr.admissao import Admissao, Tectos
from kamba_agr.degradacao import (
    FALHAS_PARA_ABRIR,
    JANELA_DO_ALERTA_S,
    LIMIAR_DO_ALERTA,
    MINIMO_PARA_ALERTAR,
    MOTIVO_429,
    MOTIVO_BREAKER,
    MOTIVO_BUDGET,
    MOTIVO_CONTRAPRESSAO,
    MOTIVO_DESTINO,
    MOTIVO_TIMEOUT,
    MOTIVOS,
    MOTIVOS_QUE_NAO_CONTAM,
    PAUSA_MS,
    DetectorDeDegradacao,
    SemDegradacao,
    backend_de,
)
from kamba_agr.estado import CAMPOS_DO_TURNO, estado_inicial
from kamba_agr.llm.erros import (
    DestinoNegado,
    FornecedorFalhou,
    OrcamentoEsgotado,
    TempoEsgotado,
    classificar,
)
from kamba_agr.metricas import (
    METRICA_DEGRADACAO_ALERTA,
    METRICA_DEGRADADOS,
    METRICA_DEGRADADOS_ACIMA,
    MetricasDoAgr,
)
from kamba_agr.validador.render import renderizar
from kamba_agr.verticais.vendedor import arestas as tabela
from kamba_agr.verticais.vendedor import nos as nos_mod
from kamba_agr.verticais.vendedor.degradado import intencoes as int_deg
from kamba_agr.verticais.vendedor.degradado import nos as nos_deg
from kamba_agr.verticais.vendedor.degradado import textos as txt
from kamba_agr.verticais.vendedor.grafo import NOS_COMPLETOS
from langgraph.checkpoint.memory import InMemorySaver

TENANT = "11111111-1111-4111-8111-111111111111"
CONTACTO = "44444444-4444-4444-8444-444444444444"


# ------------------------------------------------------------------- os duplos


class LlmQueFalha:
    """O classificador que levanta sempre. Conta as chamadas."""

    def __init__(self, erro: BaseException) -> None:
        self._erro = erro
        self.chamadas = 0

    def __call__(self, texto: str) -> str:  # noqa: ARG002
        self.chamadas += 1
        raise self._erro


class LlmQueRecupera:
    """Levanta nas primeiras `falhas` chamadas e responde a partir daí.

    Serve o critério 7: a recuperação não é uma transição que alguém escreva —
    é o disjuntor a fechar-se ao primeiro sucesso.
    """

    def __init__(self, falhas: int, intencao: str = "info_loja") -> None:
        self._restantes = falhas
        self._intencao = intencao
        self.chamadas = 0

    def __call__(self, texto: str) -> str:  # noqa: ARG002
        self.chamadas += 1
        if self._restantes > 0:
            self._restantes -= 1
            raise TempoEsgotado("o proxy nao respondeu", "router")
        return self._intencao


class BaseEmBaixo(Exception):
    """O que um erro de Postgres ou do checkpointer parece daqui.

    **Não é um `ErroDeLlm`**, e é esse o ponto do ensaio: o §14 diz que
    Postgres/checkpointer indisponível **não** é degradação.
    """


class PoliticaFixa:
    """A política `concierge` como resposta fixa (igual à do `test_concierge`)."""

    def __init__(self, activa: bool = True) -> None:
        self._activa = activa
        self.leituras: list[str] = []

    def activa(self, tenant_id: str) -> bool:
        self.leituras.append(tenant_id)
        return self._activa


class RascunhoDeEnsaio:
    """O `ServicoDeRascunho` reduzido ao que o `draft_prepare` precisa."""

    def __init__(self) -> None:
        self.abertos: list[dict[str, Any]] = []

    def abrir(self, **campos: Any) -> Any:
        self.abertos.append(campos)

        class _Aberto:
            draft_id = "d-degradado"
            publicado = True

        return _Aberto()


def detector(
    *,
    admissao: Admissao | None = None,
    relogio: Relogio | None = None,
    metricas: MetricasDoAgr | None = None,
    **extra: Any,
) -> tuple[DetectorDeDegradacao, MetricasDoAgr, Relogio]:
    """Um detector com relógio simulado e métricas próprias."""
    relogio = relogio or Relogio(0.0)
    metricas = metricas or MetricasDoAgr()
    return (
        DetectorDeDegradacao(
            admissao=admissao, relogio=relogio, metricas=metricas, **extra
        ),
        metricas,
        relogio,
    )


class _ConversaDegradada:
    """Uma conversa com checkpointer, para medir dois turnos (criterio 7)."""

    def __init__(self, **extra: Any) -> None:
        self.grafo, self.deps, self.backend, self.saida, self.ligacao = montar(
            checkpointer=InMemorySaver(), **extra
        )
        self._seq = 0

    @property
    def config(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": f"{TENANT}:{CONTACTO}"}}

    def turno(self, texto: str, *, tipo: str = "text") -> dict[str, Any]:
        self._seq += 1
        if self._seq == 1:
            entrada = estado_de(
                texto, tipo=tipo, tenant_id=TENANT, contact_id=CONTACTO
            )
        else:
            entrada = {
                "turn_id": f"wamid.turno-{self._seq}",
                "input_kind": "interactive" if tipo == "interactive" else "text",
                "messages": [{"role": "user", "content": texto}],
            }
        return asyncio.run(self.grafo.ainvoke(entrada, self.config))


# ------------------------------------------------------------- limiares medidos


class TestLimiaresDoDisjuntor(unittest.TestCase):
    """Os dois números do bloco, **medidos** na configuração real do proxy.

    O bloco dá-os como «a validar na versão fixada». Não se copiam: leem-se de
    `llm/litellm.config.yaml` e de `llm/aliases.yaml`, e o ensaio falha se
    divergirem — que é o que torna a afirmação da secção de verificação
    verificável em vez de afirmada.
    """

    def _router_settings(self, caminho: str) -> dict[str, int]:
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[3]
        linhas = (raiz / caminho).read_text(encoding="utf-8").splitlines()
        dentro = False
        lido: dict[str, int] = {}
        for linha in linhas:
            if linha.startswith("router_settings:"):
                dentro = True
                continue
            if dentro:
                if linha and not linha.startswith((" ", "\t")):
                    break
                corpo = linha.strip()
                if ":" in corpo and not corpo.startswith("-"):
                    chave, _, valor = corpo.partition(":")
                    valor = valor.strip()
                    if valor.isdigit():
                        lido[chave.strip()] = int(valor)
        return lido

    def test_o_disjuntor_usa_os_limiares_do_proxy(self) -> None:
        for caminho in ("llm/litellm.config.yaml", "llm/aliases.yaml"):
            lido = self._router_settings(caminho)
            with self.subTest(caminho=caminho):
                self.assertEqual(
                    lido.get("allowed_fails"),
                    FALHAS_PARA_ABRIR,
                    "o `allowed_fails` do proxy e o do nosso disjuntor divergiram",
                )
                self.assertEqual(
                    lido.get("cooldown_time") * 1000,
                    PAUSA_MS,
                    "o `cooldown_time` do proxy e a nossa pausa divergiram",
                )

    def test_os_limiares_do_bloco_sao_os_medidos(self) -> None:
        """O bloco escreve 3 e 30. Medido: não divergem."""
        self.assertEqual(FALHAS_PARA_ABRIR, 3)
        self.assertEqual(PAUSA_MS, 30_000)

    def test_o_limiar_do_alerta_e_o_do_criterio(self) -> None:
        self.assertEqual(LIMIAR_DO_ALERTA, 0.05)
        self.assertEqual(JANELA_DO_ALERTA_S, 900.0)


# ------------------------------------------------------------------- o detector


class TestMotivos(unittest.TestCase):
    """Os cinco motivos do critério 6, e o que o `429` teve de virar."""

    def test_sao_seis(self) -> None:
        """Cinco do critério 6, e o `destino_negado` que ele não previa."""
        self.assertEqual(len(MOTIVOS), 6)
        self.assertEqual(len(set(MOTIVOS)), 6)
        self.assertIn(MOTIVO_DESTINO, MOTIVOS)

    def test_todos_casam_a_gramatica_de_etiqueta(self) -> None:
        """É por isto que o `429` do critério é `http_429`.

        A gramática do `metricas.py` é `^[a-z][a-z0-9_]{1,62}$`: um valor que
        comece por dígito **levanta**. O ensaio prova as duas metades — que os
        cinco passam, e que o `429` cru não passava.
        """
        from kamba_agr.metricas import ETIQUETA, EtiquetaInvalida

        for motivo in MOTIVOS:
            with self.subTest(motivo=motivo):
                self.assertRegex(motivo, ETIQUETA)
        self.assertIsNone(ETIQUETA.match("429"))
        metricas = MetricasDoAgr()
        with self.assertRaises(EtiquetaInvalida):
            metricas.contar(METRICA_DEGRADADOS, "429")

    def test_o_timeout_o_orcamento_e_o_429_tem_motivo_proprio(self) -> None:
        self.assertEqual(
            deg.motivo_do_erro(TempoEsgotado("tempo", "router")), MOTIVO_TIMEOUT
        )
        self.assertEqual(
            deg.motivo_do_erro(OrcamentoEsgotado("budget", "router")), MOTIVO_BUDGET
        )
        self.assertEqual(
            deg.motivo_do_erro(FornecedorFalhou("ritmo", "router", 429)), MOTIVO_429
        )
        self.assertEqual(
            deg.motivo_do_erro(FornecedorFalhou("avaria", "router", 503)),
            MOTIVO_BREAKER,
        )

    def test_o_destino_negado_nao_e_avaria_do_modelo(self) -> None:
        """Achado C4: caía no ramo de omissão e saía `breaker`.

        Um `DestinoNegado` é a recusa do *gate* de destino (ADR-008) — uma
        barreira de soberania a funcionar, e **permanente** até ao KAM-069, não
        uma avaria transitória. Dizer `breaker` punha o painel a afirmar «o
        modelo ficou inalcançável» sobre uma recusa de conformidade.
        """
        erro = DestinoNegado("destino nao autorizado", "router")
        self.assertEqual(deg.motivo_do_erro(erro), MOTIVO_DESTINO)
        self.assertIn(MOTIVO_DESTINO, MOTIVOS_QUE_NAO_CONTAM)

    def test_o_destino_negado_nao_abre_o_disjuntor(self) -> None:
        """E a segunda metade: não conta no disjuntor, por muitas que sejam."""
        det, metricas, _ = detector()
        for _ in range(FALHAS_PARA_ABRIR * 2):
            self.assertEqual(
                det.registar_falha(TENANT, DestinoNegado("nao autorizado", "router")),
                MOTIVO_DESTINO,
            )
        self.assertIsNone(det.motivo_antes_do_turno(TENANT))
        self.assertNotIn(METRICA_DEGRADACAO_ALERTA, metricas.exposicao())

    def test_o_classificar_do_gateway_poe_o_estado_na_excepcao(self) -> None:
        """O 429 chega aqui pelo `estado_http`, e não por um `resultado` novo.

        O `RESULTADOS` é o domínio fechado de `dat.llm_call_log.resultado`, com
        `CHECK` na revisão `0023`: um valor novo era uma migração.
        """
        erro = classificar(429, {"error": {"type": "rate_limit"}}, "router")
        self.assertEqual(erro.estado_http, 429)
        self.assertEqual(deg.motivo_do_erro(erro), MOTIVO_429)
        orcamento = classificar(
            422, {"error": {"type": "budget_exceeded"}}, "router"
        )
        self.assertEqual(deg.motivo_do_erro(orcamento), MOTIVO_BUDGET)


class TestNaoDegradaComOQueNaoEDoLlm(unittest.TestCase):
    """**A barreira que não se simplifica**: Postgres em baixo não é degradação."""

    def test_o_detector_recusa_classificar_o_que_nao_e_erro_de_llm(self) -> None:
        det, _, _ = detector()
        for erro in (BaseEmBaixo("a base caiu"), RuntimeError("qualquer coisa")):
            with self.subTest(erro=type(erro).__name__):
                with self.assertRaises(TypeError):
                    det.motivo_do_erro(erro)
                with self.assertRaises(TypeError):
                    det.registar_falha(TENANT, erro)

    def test_o_sem_degradacao_recusa_o_mesmo(self) -> None:
        """A omissão não é a porta larga: recusa pela mesma regra."""
        with self.assertRaises(TypeError):
            SemDegradacao().motivo_do_erro(BaseEmBaixo("a base caiu"))

    def test_um_erro_da_base_no_turno_nao_degrada_e_nao_envia(self) -> None:
        """O turno **falha** e a mensagem fica na fila. Nada sai ao cliente."""
        det, metricas, _ = detector()
        classificador = LlmQueFalha(BaseEmBaixo("a base caiu"))
        grafo, _, _, saida, _ = montar(
            classificador=classificador, degradacao=det, metricas=MetricasDoAgr()
        )
        with self.assertRaises(BaseEmBaixo):
            correr(grafo, estado_de("bom dia", tenant_id=TENANT))
        self.assertEqual(saida.enviadas, [], "saiu mensagem num turno que falhou")
        self.assertNotIn(
            f"{METRICA_DEGRADADOS}:{MOTIVO_BREAKER}",
            metricas.exposicao(),
            "a base em baixo foi contada como turno degradado",
        )

    def test_um_erro_da_base_nao_deixa_a_porta_fechada_para_o_turno_seguinte(
        self,
    ) -> None:
        """**Achado C7**, medido pelo grafo e não pelo detector sozinho.

        O `pode_chamar_o_llm` consome a tentativa de meio-aberto; se o
        classificador levantar algo que não é do modelo, a excepção sobe — e
        bem — mas a tentativa ficava pendurada pelo prazo da pausa, e os turnos
        desse intervalo degradavam com `motivo="breaker"`.
        """
        det, metricas, relogio = detector()
        for _ in range(FALHAS_PARA_ABRIR):
            det.registar_falha(TENANT, TempoEsgotado("tempo", "router"))
        relogio.avancar(PAUSA_MS / 1000 + 1)
        mau = LlmQueFalha(BaseEmBaixo("a base caiu"))
        grafo, _, _, _, _ = montar(classificador=mau, degradacao=det)
        with self.assertRaises(BaseEmBaixo):
            correr(grafo, estado_de("bom dia", tenant_id=TENANT))
        # A porta tem de ficar aberta para o turno seguinte: o que falhou não
        # disse nada sobre a saúde do modelo.
        self.assertTrue(
            det.pode_chamar_o_llm(TENANT),
            "a tentativa de meio-aberto ficou pendurada por um erro da base",
        )


class TestDisjuntorDoLlm(unittest.TestCase):
    """O *circuit breaker*: abre às três falhas, fecha ao primeiro sucesso."""

    def test_abre_as_falhas_do_proxy_e_nao_antes(self) -> None:
        det, metricas, _ = detector()
        for _ in range(FALHAS_PARA_ABRIR - 1):
            det.registar_falha(TENANT, TempoEsgotado("tempo", "router"))
            self.assertIsNone(det.motivo_antes_do_turno(TENANT))
        det.registar_falha(TENANT, TempoEsgotado("tempo", "router"))
        self.assertEqual(det.motivo_antes_do_turno(TENANT), MOTIVO_BREAKER)
        self.assertIn(METRICA_DEGRADACAO_ALERTA, metricas.exposicao())

    def test_fecha_ao_primeiro_sucesso_e_o_turno_seguinte_e_normal(self) -> None:
        """Critério 7, a metade que vive no disjuntor."""
        det, _, _ = detector()
        for _ in range(FALHAS_PARA_ABRIR):
            det.registar_falha(TENANT, TempoEsgotado("tempo", "router"))
        self.assertEqual(det.motivo_antes_do_turno(TENANT), MOTIVO_BREAKER)
        det.registar_sucesso(TENANT)
        self.assertIsNone(det.motivo_antes_do_turno(TENANT))

    def test_a_pausa_acaba_e_deixa_passar_uma_tentativa(self) -> None:
        det, _, relogio = detector()
        for _ in range(FALHAS_PARA_ABRIR):
            det.registar_falha(TENANT, TempoEsgotado("tempo", "router"))
        self.assertFalse(det.pode_chamar_o_llm(TENANT))
        relogio.avancar(PAUSA_MS / 1000 + 1)
        self.assertTrue(det.pode_chamar_o_llm(TENANT), "a pausa acabou e a porta ficou fechada")

    def test_o_disjuntor_de_um_tenant_nao_degrada_outro(self) -> None:
        """Achado C3: era um disjuntor global e o orçamento é por chave do tenant.

        Três `OrcamentoEsgotado` de um *tenant* punham **toda** a réplica em modo
        determinístico durante a pausa — o oposto do anti-vizinho-ruidoso do
        §15.2 regra 2. O orçamento é da chave virtual dele (§13.3), o ritmo é por
        chave, e o *gate* de destino decide por `tenant_id`: todas as falhas que
        este detector vê são do *tenant*.
        """
        det, _, _ = detector()
        for _ in range(FALHAS_PARA_ABRIR):
            det.registar_falha(TENANT, OrcamentoEsgotado("sem orcamento", "router"))
        self.assertEqual(det.motivo_antes_do_turno(TENANT), MOTIVO_BREAKER)
        self.assertIsNone(
            det.motivo_antes_do_turno("99999999-9999-4999-8999-999999999999"),
            "o disjuntor de um tenant degradou outro",
        )

    def test_a_chave_do_disjuntor_leva_o_tenant(self) -> None:
        outro = "99999999-9999-4999-8999-999999999999"
        self.assertNotEqual(backend_de(TENANT), backend_de(outro))
        self.assertTrue(backend_de(TENANT).endswith(TENANT))

    def test_o_absolver_larga_a_tentativa_sem_tocar_na_contagem(self) -> None:
        """Achado C7: o `pode_chamar_o_llm` consome a tentativa de meio-aberto.

        Se quem a levou não a julgar — uma excepção que **não** é do modelo —, a
        porta ficava fechada pelo prazo da pausa, e os turnos desse intervalo
        nasciam normais e degradavam com `motivo="breaker"`.
        """
        det, _, relogio = detector()
        for _ in range(FALHAS_PARA_ABRIR):
            det.registar_falha(TENANT, TempoEsgotado("tempo", "router"))
        relogio.avancar(PAUSA_MS / 1000 + 1)
        self.assertTrue(det.pode_chamar_o_llm(TENANT))
        self.assertFalse(det.pode_chamar_o_llm(TENANT), "a segunda passou")
        det.absolver(TENANT)
        self.assertTrue(
            det.pode_chamar_o_llm(TENANT), "o absolver nao largou a tentativa"
        )

    def test_o_aberto_nao_consome_a_tentativa_de_meio_aberto(self) -> None:
        """Ler o painel não é decidir: o `motivo_antes_do_turno` não muta."""
        det, _, relogio = detector()
        for _ in range(FALHAS_PARA_ABRIR):
            det.registar_falha(TENANT, TempoEsgotado("tempo", "router"))
        relogio.avancar(PAUSA_MS / 1000 + 1)
        for _ in range(3):
            self.assertIsNone(det.motivo_antes_do_turno(TENANT))
        self.assertTrue(det.pode_chamar_o_llm(TENANT))


class TestContrapressao(unittest.TestCase):
    """O critério 8: **as duas** condições, e nenhuma sozinha."""

    def _admissao(self, em_curso: int, a_espera: int) -> Admissao:
        admissao = Admissao(tectos=Tectos(tecto_por_tenant=3, limiar_de_contrapressao=10))
        admissao._em_curso[TENANT] = em_curso  # noqa: SLF001 — o contador é privado
        admissao._a_espera = a_espera  # noqa: SLF001
        return admissao

    def test_tecto_cheio_e_fila_acima_do_limiar_degrada(self) -> None:
        det, _, _ = detector(admissao=self._admissao(3, 10))
        self.assertEqual(det.motivo_antes_do_turno(TENANT), MOTIVO_CONTRAPRESSAO)

    def test_tecto_cheio_sozinho_nao_degrada(self) -> None:
        """É o anti-vizinho-ruidoso a funcionar, com a plataforma folgada."""
        det, _, _ = detector(admissao=self._admissao(3, 1))
        self.assertIsNone(det.motivo_antes_do_turno(TENANT))

    def test_fila_acima_do_limiar_sozinha_nao_degrada(self) -> None:
        """Carga da plataforma não é carga deste *tenant*."""
        det, _, _ = detector(admissao=self._admissao(0, 100))
        self.assertIsNone(det.motivo_antes_do_turno(TENANT))

    def test_tecto_a_zero_e_sem_tecto_e_nao_degrada(self) -> None:
        admissao = Admissao(tectos=Tectos(tecto_por_tenant=0, limiar_de_contrapressao=10))
        admissao._a_espera = 100  # noqa: SLF001
        det, _, _ = detector(admissao=admissao)
        self.assertIsNone(det.motivo_antes_do_turno(TENANT))

    def test_limiar_a_zero_nao_poe_toda_a_fila_em_contrapressao(self) -> None:
        admissao = Admissao(tectos=Tectos(tecto_por_tenant=1, limiar_de_contrapressao=0))
        admissao._em_curso[TENANT] = 1  # noqa: SLF001
        det, _, _ = detector(admissao=admissao)
        self.assertIsNone(det.motivo_antes_do_turno(TENANT))

    def test_o_tecto_lido_e_o_da_admissao_e_nao_o_do_ambiente(self) -> None:
        """A propriedade `tectos` existe para isto: ler **este** `Admissao`."""
        admissao = self._admissao(2, 10)
        self.assertEqual(admissao.tectos.tecto_por_tenant, 3)
        det, _, _ = detector(admissao=admissao)
        self.assertIsNone(det.motivo_antes_do_turno(TENANT))


class TestJanelaEAlerta(unittest.TestCase):
    """O critério 6: o contador por motivo e o alerta de > 5% em 15 min."""

    def test_a_metrica_leva_o_motivo_e_nao_o_tenant(self) -> None:
        det, metricas, _ = detector()
        det.registar_turno(TENANT, "t1", MOTIVO_TIMEOUT)
        det.registar_turno(TENANT, "t2", MOTIVO_BUDGET)
        exposicao = metricas.exposicao()
        self.assertIn(f'{METRICA_DEGRADADOS}{{motivo="{MOTIVO_TIMEOUT}"}} 1', exposicao)
        self.assertIn(f'{METRICA_DEGRADADOS}{{motivo="{MOTIVO_BUDGET}"}} 1', exposicao)
        self.assertNotIn(TENANT, exposicao, "o tenant_id chegou a exposicao")

    def test_um_turno_conta_uma_vez_mesmo_registado_duas(self) -> None:
        """O `turn_id` é o que impede o denominador de inflacionar."""
        det, metricas, _ = detector()
        det.registar_turno(TENANT, "t1", None)
        det.registar_turno(TENANT, "t1", MOTIVO_TIMEOUT)
        self.assertEqual(det.proporcao(TENANT), 1.0)
        self.assertIn(f'{METRICA_DEGRADADOS}{{motivo="{MOTIVO_TIMEOUT}"}} 1', metricas.exposicao())

    def test_a_degradacao_de_um_turno_nao_marca_o_turno_do_lado(self) -> None:
        """Com três turnos em voo, a promoção vai ao `turn_id` certo."""
        det, _, _ = detector()
        for turno in ("t1", "t2", "t3"):
            det.registar_turno(TENANT, turno, None)
        det.registar_turno(TENANT, "t2", MOTIVO_TIMEOUT)
        self.assertAlmostEqual(det.proporcao(TENANT), 1 / 3)

    def test_nao_alerta_abaixo_do_minimo_de_turnos(self) -> None:
        """Um único turno degradado dá 100% e não é sinal."""
        det, _, _ = detector()
        self.assertFalse(det.registar_turno(TENANT, "t1", MOTIVO_TIMEOUT))
        self.assertEqual(det.proporcao(TENANT), 1.0)

    def test_alerta_acima_do_limiar_na_janela(self) -> None:
        det, metricas, _ = detector()
        for indice in range(MINIMO_PARA_ALERTAR - 1):
            self.assertFalse(det.registar_turno(TENANT, f"n{indice}", None))
        # O primeiro degradado fecha o mínimo: 1/20 = 5%, que **não** é > 5%.
        self.assertFalse(det.registar_turno(TENANT, "d0", MOTIVO_TIMEOUT))
        self.assertAlmostEqual(det.proporcao(TENANT), 1 / MINIMO_PARA_ALERTAR)
        self.assertNotIn(METRICA_DEGRADADOS_ACIMA, metricas.exposicao())
        # O segundo passa: 2/21 > 5%.
        self.assertTrue(det.registar_turno(TENANT, "d1", MOTIVO_TIMEOUT))

    def test_o_alerta_tem_efeito_e_nao_so_valor_de_retorno(self) -> None:
        """Achado C5: o booleano era calculado e descartado pelos dois chamadores.

        **O ensaio anterior media o valor de retorno de um método**, e passaria
        inalterado se nenhum caminho de execução o chamasse. O que se mede agora
        é que a passagem do limiar **conta** — a forma que o KAM-027 deu ao
        «emite alerta» do seu critério 6 e o KAM-114 ao dele, porque não há
        sistema de alertas neste repositório.
        """
        det, metricas, _ = detector()
        for indice in range(MINIMO_PARA_ALERTAR):
            det.registar_turno(TENANT, f"d{indice}", MOTIVO_TIMEOUT)
        self.assertIn(f"{METRICA_DEGRADADOS_ACIMA} 1", metricas.exposicao())

    def test_o_alerta_conta_num_turno_que_corre_o_grafo(self) -> None:
        """E o efeito mede-se **pelo grafo**, não pelo detector sozinho.

        É a diferença entre «a função devolve True» e «alguém a chama»: o
        `ingest` é o único nó por onde todos os turnos passam.
        """
        det, metricas, _ = detector(minimo_para_alertar=2)
        classificador = LlmQueFalha(TempoEsgotado("tempo", "router"))
        for indice in range(3):
            grafo, _, _, _, _ = montar(
                classificador=classificador, degradacao=det
            )
            correr(
                grafo,
                estado_de("bom dia", tenant_id=TENANT, wamid=f"wamid.a{indice}"),
            )
        self.assertIn(METRICA_DEGRADADOS_ACIMA, metricas.exposicao())

    def test_um_turno_sem_turn_id_levanta(self) -> None:
        """Achado P1: o `or ""` colapsava os turnos em voo numa entrada."""
        det, _, _ = detector()
        with self.assertRaises(ValueError):
            det.registar_turno(TENANT, "", None)

    def test_a_janela_desliza_e_o_que_saiu_deixa_de_contar(self) -> None:
        det, _, relogio = detector()
        for indice in range(MINIMO_PARA_ALERTAR):
            det.registar_turno(TENANT, f"d{indice}", MOTIVO_TIMEOUT)
        self.assertEqual(det.proporcao(TENANT), 1.0)
        relogio.avancar(JANELA_DO_ALERTA_S + 1)
        self.assertEqual(det.proporcao(TENANT), 0.0)
        self.assertFalse(det.registar_turno(TENANT, "novo", None))

    def test_a_janela_nao_cresce_com_um_tenant_por_chave(self) -> None:
        """A poda é de **todos** os *tenants*, não só do que acabou de falar."""
        det, _, relogio = detector()
        for indice in range(50):
            det.registar_turno(f"tenant-{indice}", "t", None)
        self.assertEqual(len(det._turnos), 50)  # noqa: SLF001
        relogio.avancar(JANELA_DO_ALERTA_S + 1)
        det.registar_turno("tenant-novo", "t", None)
        self.assertEqual(len(det._turnos), 1)  # noqa: SLF001

    def test_um_motivo_fora_dos_cinco_levanta(self) -> None:
        det, _, _ = detector()
        with self.assertRaises(ValueError):
            det.registar_turno(TENANT, "t1", "nao_e_motivo")


# ------------------------------------------------- o sub-grafo: contrato e nos


class TestContratoDoSubGrafo(unittest.TestCase):
    """O que o KAM-037 acrescenta à tabela, e o que ele **não** pode mexer."""

    def test_o_no_novo_e_um_e_esta_na_tabela_e_no_grafo(self) -> None:
        self.assertIn("degraded_menu", tabela.NOS)
        self.assertIn("degraded_menu", NOS_COMPLETOS)
        self.assertEqual(set(tabela.NOS), set(NOS_COMPLETOS))

    def test_as_arestas_do_ticket_sao_duas(self) -> None:
        self.assertEqual(len(tabela.do_degradado()), 2)
        self.assertEqual(
            {(a.de, a.para) for a in tabela.do_degradado()},
            {("classify", "degraded_menu"), ("degraded_menu", "validate")},
        )

    def test_o_73_continua_a_ter_trinta_e_nove_linhas_e_quarenta_e_duas_arestas(
        self,
    ) -> None:
        """**O filtro do `do_73` era por negação de um valor, e isto mede-o.**

        Com `a.fonte != FONTE_DO_CONCIERGE`, as duas arestas deste ticket
        contavam como sendo do §7.3 e a contagem passava de 42 para 44 sem
        ninguém notar.
        """
        self.assertEqual(len(tabela.do_73()), 42)
        self.assertEqual(len({a.linha for a in tabela.do_73()}), tabela.LINHAS_DO_73)
        self.assertEqual(len(tabela.do_concierge()), 4)
        self.assertEqual(
            len(tabela.ARESTAS),
            len(tabela.do_73()) + len(tabela.do_concierge()) + len(tabela.do_degradado()),
        )

    def test_o_semver_do_grafo_subiu_no_minor(self) -> None:
        """Um nó entrou: sobe no *minor*. É a metade do eval-gate que se entrega."""
        self.assertEqual(tabela.VERSAO_DO_GRAFO, "1.2.0")

    def test_o_grafo_compilado_tem_as_arestas_novas(self) -> None:
        grafo, _, _, _, _ = montar()
        self.assertEqual(tabela.pares(), tabela.pares_do_compilado(grafo))
        self.assertIn("degraded_menu", tabela.nos_do_compilado(grafo))

    def test_o_mapa_do_classify_tem_a_chave_do_menu(self) -> None:
        self.assertEqual(tabela.mapa_de("classify")["menu"], "degraded_menu")

    def test_dois_nos_com_o_mesmo_nome_nao_se_sobrepoem_em_silencio(self) -> None:
        """A junção das duas tabelas levanta em vez de substituir."""
        self.assertEqual(len(NOS_COMPLETOS), len(tabela.NOS))
        self.assertTrue(set(nos_deg.NOS_DEGRADADOS).issubset(set(NOS_COMPLETOS)))


class TestTextosEIdentificadores(unittest.TestCase):
    """Critério 2 e critério 5 sobre os textos: limites e renderização."""

    def test_as_opcoes_sao_tres_e_cabem_no_tecto_do_outbound(self) -> None:
        """Achado C6: eram quatro, e o Outbound recusa acima de três.

        Lê-se o `MAXIMO_DE_BOTOES` do `contrato.ts` **do ficheiro** e não de uma
        constante nossa: é o consumidor que fixa o tecto, e uma cópia aqui
        divergia dele no dia em que a Meta mudasse de limite.
        """
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[3]
        contrato = (
            raiz / "packages" / "core-ts" / "src" / "outbound" / "contrato.ts"
        ).read_text(encoding="utf-8")
        achado = re.search(r"MAXIMO_DE_BOTOES\s*=\s*(\d+)", contrato)
        self.assertIsNotNone(achado, "o contrato do Outbound mudou de forma")
        tecto = int(achado.group(1))
        self.assertEqual(tecto, txt.MAX_BOTOES_DO_MENU)
        self.assertEqual(len(txt.OPCOES), 3)
        self.assertLessEqual(len(txt.OPCOES), tecto)

    def test_cada_opcao_tem_rotulo_em_pt_sem_digitos(self) -> None:
        """A outra metade do C6: o `Corpo` do Outbound exige `{id, titulo}`."""
        self.assertEqual(set(txt.ROTULO_DA_OPCAO), set(txt.OPCOES))
        for opcao, rotulo in txt.ROTULO_DA_OPCAO.items():
            with self.subTest(opcao=opcao):
                self.assertTrue(rotulo.strip())
                self.assertNotRegex(rotulo, r"\d")

    def test_todos_os_textos_renderizam_sem_facts(self) -> None:
        """Critério 5: **0 números fora de *facts***, medido e não afirmado.

        O `renderizar` levanta num bloco `text` com dígitos **ou** com prosa
        numérica por extenso. Passar os textos todos por ele é o que torna a
        regra do cabeçalho do `textos.py` verificável.
        """
        for texto in txt.TEXTOS:
            with self.subTest(texto=texto[:40]):
                saida = renderizar([{"type": "text", "text": texto}])
                self.assertEqual(saida.texto, texto)

    def test_a_tupla_de_textos_tem_todos_os_textos_do_modulo(self) -> None:
        """Um texto novo que não entre na tupla falha aqui, não em produção."""
        declarados = {
            valor
            for nome, valor in vars(txt).items()
            if nome.startswith("MSG_") and isinstance(valor, str)
        }
        self.assertEqual(declarados, set(txt.TEXTOS))

    def test_os_identificadores_levam_o_prefixo_e_sao_distintos(self) -> None:
        for opcao in txt.OPCOES:
            with self.subTest(opcao=opcao):
                self.assertTrue(opcao.startswith(txt.PREFIXO_DA_OPCAO))
        self.assertEqual(len(txt.OPCOES), len(set(txt.OPCOES)))

    def test_cada_opcao_abre_uma_das_nove_intencoes_e_nao_uma_decima(self) -> None:
        """O modo não acrescenta vocabulário ao classificador."""
        for opcao, intencao in int_deg.INTENCAO_DA_OPCAO.items():
            with self.subTest(opcao=opcao):
                self.assertIn(intencao, tabela.INTENCOES)
        self.assertEqual(set(int_deg.INTENCAO_DA_OPCAO), set(txt.OPCOES))

    def test_as_servidas_sao_intencoes_e_estao_na_lista_do_criterio(self) -> None:
        for intencao in int_deg.SERVIDAS:
            with self.subTest(intencao=intencao):
                self.assertIn(intencao, tabela.INTENCOES)
        self.assertEqual(
            set(int_deg.SERVIDAS),
            {"confirmar", "pagamento_estado", "encomenda", "info_loja", "humano"},
        )
        self.assertEqual(set(int_deg.DE_CATALOGO) & set(int_deg.SERVIDAS), set())


class TestIntencaoSemLlm(unittest.TestCase):
    """Critério 4: a intenção por identificador e por palavra-chave."""

    def test_o_botao_de_confirmacao_vence_o_texto(self) -> None:
        self.assertEqual(
            int_deg.intencao_sem_llm("confirm:c_1", "quero falar com um colega"),
            "confirmar",
        )

    def test_cada_opcao_do_menu_decide(self) -> None:
        for opcao, esperada in int_deg.INTENCAO_DA_OPCAO.items():
            with self.subTest(opcao=opcao):
                self.assertEqual(int_deg.intencao_sem_llm(opcao, ""), esperada)

    def test_o_rotulo_do_botao_nao_decide_por_acidente(self) -> None:
        """O botão vem antes do texto, e é por isso que isto passa.

        Uma mensagem interactiva traz o rótulo como texto; a ler o texto
        primeiro, «Falar com um colega» casava o padrão `humano` e dava a
        resposta certa pela razão errada.
        """
        self.assertEqual(
            int_deg.intencao_sem_llm(txt.OPCAO_LOJA, "Falar com um colega"),
            "info_loja",
        )

    def test_as_palavras_chave_decidem_sem_botao(self) -> None:
        self.assertEqual(int_deg.intencao_sem_llm("", "qual o horario da loja?"), "info_loja")
        self.assertEqual(int_deg.intencao_sem_llm("", "o meu pedido ja saiu?"), "encomenda")

    def test_texto_livre_nao_reconhecido_da_outro_e_nao_inventa(self) -> None:
        self.assertEqual(int_deg.intencao_sem_llm("", "obrigado"), "outro")
        self.assertFalse(int_deg.serve("outro"))

    def test_a_opcao_do_menu_vale_com_o_modelo_de_pe(self) -> None:
        """**Achado C1, e era crítico.** O botão fica no ecrã do WhatsApp.

        O `degradado` é um campo do turno; o botão não. Com o mapa consultado só
        no caminho degradado, o turno seguinte — com o modelo recuperado — não
        reconhecia os identificadores que nós próprios emitimos: o `menu:humano`
        deixava de abrir *handoff* e o id cru ia ao modelo como texto do cliente.

        Aqui o detector **não** degrada e o classificador está ligado: mede-se
        que ele nunca é chamado e que a intenção sai certa.
        """
        for opcao, esperada in int_deg.INTENCAO_DA_OPCAO.items():
            with self.subTest(opcao=opcao):
                classificador = LlmQueFalha(
                    AssertionError("o modelo nao devia ser chamado")
                )
                hnd = Handoff()
                grafo, _, _, saida, _ = montar(
                    classificador=classificador, hnd=hnd
                )
                final = correr(
                    grafo,
                    estado_de(opcao, tipo="interactive", tenant_id=TENANT),
                )
                self.assertIsNone(final["degradado"])
                self.assertEqual(final["intent"], esperada)
                self.assertEqual(classificador.chamadas, 0)
                if esperada == "humano":
                    self.assertEqual(final["handoff_motivo"], "pedido_humano")
                    self.assertTrue(hnd.abertos)
                else:
                    self.assertEqual(len(saida.enviadas), 1)

    def test_a_referencia_sozinha_e_uma_consulta_de_pedido(self) -> None:
        """A segunda metade do C2: sem isto o menu era um ciclo fechado."""
        self.assertTrue(int_deg.so_uma_referencia("ABC-123"))
        self.assertTrue(int_deg.so_uma_referencia(" ABC-123? "))
        self.assertEqual(int_deg.intencao_sem_llm("", "ABC-123"), "encomenda")
        self.assertTrue(int_deg.serve("encomenda"))
        # E **não** apanha uma frase qualquer com um número dentro.
        for inocente in ("quero 2 camisas", "bom dia", "o A-1 e o B-2"):
            with self.subTest(texto=inocente):
                self.assertFalse(int_deg.so_uma_referencia(inocente))

    def test_o_falar_com_humano_antigo_continua_a_valer(self) -> None:
        from kamba_agr.verticais.vendedor.nos import BOTAO_HUMANO

        self.assertEqual(int_deg.intencao_sem_llm(BOTAO_HUMANO, ""), "humano")


# ----------------------------------------------------- os oito criterios, a ponta


class TestCriterio1(unittest.TestCase):
    """«≤ 1 turno, sem excepção e sem mensagem em falta» nos três modos."""

    def _erros(self) -> dict[str, BaseException]:
        return {
            MOTIVO_TIMEOUT: TempoEsgotado("o proxy nao respondeu", "router"),
            MOTIVO_429: FornecedorFalhou("o proxy respondeu 429", "router", 429),
            MOTIVO_BUDGET: OrcamentoEsgotado("o orcamento esgotou-se", "router"),
        }

    def test_os_tres_modos_de_falha_respondem_no_mesmo_turno(self) -> None:
        for motivo, erro in self._erros().items():
            with self.subTest(motivo=motivo):
                det, metricas, _ = detector()
                classificador = LlmQueFalha(erro)
                grafo, _, _, saida, _ = montar(
                    classificador=classificador, degradacao=det
                )
                final = correr(grafo, estado_de("bom dia", tenant_id=TENANT))
                self.assertEqual(classificador.chamadas, 1)
                self.assertEqual(
                    len(saida.enviadas), 1, "o turno degradado nao respondeu"
                )
                self.assertEqual(final["degradado"], {"motivo": motivo})
                self.assertIn(
                    f'{METRICA_DEGRADADOS}{{motivo="{motivo}"}} 1', metricas.exposicao()
                )

    def test_zero_turnos_sem_resposta_em_cem_execucoes(self) -> None:
        """**Cem, à letra.** O critério escreve cem e noventa não cumpre.

        As cem correm os três modos por rotação, para que nenhum fique sem
        execução — e o disjuntor fica **desligado** (`falhas` muito alto), porque
        o que este critério mede é «sem excepção», não o disjuntor: com ele a
        abrir à terceira falha, as outras noventa e sete nunca chegavam ao
        `except` e o critério media outra coisa. O disjuntor tem ensaio próprio.
        """
        erros = list(self._erros().values())
        det, _, _ = detector(disjuntor=_disjuntor_que_nunca_abre())
        execucoes = 100
        enviadas = 0
        for indice in range(execucoes):
            classificador = LlmQueFalha(erros[indice % len(erros)])
            grafo, _, _, saida, _ = montar(classificador=classificador, degradacao=det)
            final = correr(grafo, estado_de("bom dia", tenant_id=TENANT))
            self.assertTrue(final.get("degradado"), f"execucao {indice} nao degradou")
            enviadas += len(saida.enviadas)
        self.assertEqual(
            enviadas, execucoes, "houve turnos sem resposta em cem execucoes"
        )

    def test_o_turno_degradado_nao_vai_ao_modelo_quando_ja_nasceu_degradado(
        self,
    ) -> None:
        """O disjuntor aberto poupa a ida: zero chamadas ao classificador."""
        det, _, _ = detector()
        _abrir_o_disjuntor(det)
        classificador = LlmQueFalha(TempoEsgotado("tempo", "router"))
        grafo, _, _, saida, _ = montar(classificador=classificador, degradacao=det)
        final = correr(grafo, estado_de("bom dia", tenant_id=TENANT))
        self.assertEqual(classificador.chamadas, 0)
        self.assertEqual(final["degradado"], {"motivo": MOTIVO_BREAKER})
        self.assertEqual(len(saida.enviadas), 1)


def _abrir_o_disjuntor(det: DetectorDeDegradacao) -> None:
    """Põe o disjuntor do LLM aberto: o turno seguinte nasce degradado."""
    for _ in range(FALHAS_PARA_ABRIR):
        det.registar_falha(TENANT, TempoEsgotado("tempo", "router"))


def _disjuntor_que_nunca_abre():
    from kamba_agr.tls.disjuntor import Disjuntor

    return Disjuntor(falhas=10**6, pausa_ms=0)


class TestCriterio2(unittest.TestCase):
    """O que o modo serve: menu, lista, estado do pedido, loja e humano."""

    def _grafo_degradado(self, **extra: Any):
        det, _, _ = detector()
        _abrir_o_disjuntor(det)
        return montar(degradacao=det, **extra)

    def test_o_menu_principal_sai_com_tres_botoes_no_primeiro_turno(self) -> None:
        grafo, _, _, saida, _ = self._grafo_degradado()
        correr(grafo, estado_de("bom dia", tenant_id=TENANT))
        texto, _, botoes = saida.enviadas[0]
        self.assertIn(txt.MSG_MENU, texto)
        self.assertEqual(botoes, txt.OPCOES)
        self.assertLessEqual(len(botoes), txt.MAX_BOTOES_DO_MENU)

    def test_um_pedido_de_catalogo_recebe_a_explicacao_e_a_lista(self) -> None:
        grafo, _, _, saida, _ = self._grafo_degradado()
        correr(grafo, estado_de("tem camisas azuis?", tenant_id=TENANT))
        texto, _, botoes = saida.enviadas[0]
        self.assertIn(txt.MSG_SEM_CATALOGO, texto)
        self.assertEqual(botoes, txt.OPCOES)
        self.assertLessEqual(len(botoes), txt.MAX_BOTOES_DO_MENU)

    def test_o_horario_e_a_morada_passam_pelo_tools_info(self) -> None:
        grafo, _, _, saida, _ = self._grafo_degradado()
        final = correr(grafo, estado_de("qual o horario da loja?", tenant_id=TENANT))
        self.assertEqual(final["intent"], "info_loja")
        self.assertEqual(len(saida.enviadas), 1)
        # O `get_store_info` devolve nome e zona; o resto tem dígitos e cala-se
        # (dívida 124, credor KAM-032).
        self.assertIn("Casa Bela", saida.enviadas[0][0])

    def test_falar_com_humano_vai_a_handoff_com_motivo(self) -> None:
        hnd = Handoff()
        grafo, _, _, saida, _ = self._grafo_degradado(hnd=hnd)
        final = correr(
            grafo,
            estado_de(txt.OPCAO_HUMANO, tipo="interactive", tenant_id=TENANT),
        )
        self.assertEqual(final["intent"], "humano")
        self.assertEqual(final["handoff_motivo"], "pedido_humano")
        self.assertTrue(hnd.abertos, "o handoff nao abriu em modo degradado")

    def test_o_estado_do_pedido_e_servido_pelo_order_status(self) -> None:
        """**Achado C9: este ensaio passava com o comportamento oposto ao nome.**

        Afirmava a `intent` e que *alguma* mensagem saiu, e o que saía era «Não
        encontrei esse artigo no catálogo da loja» — porque `ABC-123` não existe
        no *fake*. Agora o pedido existe, e mede-se o **texto**.
        """
        grafo, _, backend, saida, _ = self._grafo_degradado()
        backend.encomendas["ABC-123"] = (CONTACTO, "pago")
        final = correr(
            grafo,
            estado_de(
                "o meu pedido ABC-123 ja saiu?",
                tenant_id=TENANT,
                contact_id=CONTACTO,
            ),
        )
        self.assertEqual(final["intent"], "encomenda")
        self.assertEqual(final["avisos"], ())
        self.assertEqual(len(saida.enviadas), 1)
        self.assertIn("pago", saida.enviadas[0][0])

    def test_um_toque_em_o_meu_pedido_pergunta_a_referencia(self) -> None:
        """**Achado C2, e era a opção mais visível do menu.**

        O `order_status` procura a referência **no texto do cliente**, e no turno
        de um toque o texto do turno *é* o identificador do botão. Antes disto, a
        resposta era a frase de catálogo — «Não encontrei esse artigo no catálogo
        da loja» — a quem tocou em «O meu pedido».
        """
        grafo, _, _, saida, _ = self._grafo_degradado()
        final = correr(
            grafo,
            estado_de(txt.OPCAO_PEDIDO, tipo="interactive", tenant_id=TENANT),
        )
        self.assertEqual(final["intent"], "encomenda")
        self.assertEqual(final["avisos"], (tabela.REFERENCIA_EM_FALTA,))
        self.assertEqual(len(saida.enviadas), 1)
        texto = saida.enviadas[0][0]
        self.assertIn("referencia do pedido", texto)
        self.assertNotIn("catalogo", texto)

    def test_o_ciclo_do_menu_fecha_se_com_a_referencia(self) -> None:
        """Toque, pergunta, referência, resposta. Era um ciclo sem saída."""
        det, _, _ = detector()
        _abrir_o_disjuntor(det)
        conversa = _ConversaDegradada(degradacao=det)
        conversa.backend.encomendas["ABC-123"] = (CONTACTO, "pendente")
        primeiro = conversa.turno(txt.OPCAO_PEDIDO, tipo="interactive")
        self.assertEqual(primeiro["avisos"], (tabela.REFERENCIA_EM_FALTA,))
        segundo = conversa.turno("ABC-123")
        self.assertEqual(segundo["intent"], "encomenda")
        self.assertEqual(segundo["avisos"], ())
        self.assertIn("pendente", conversa.saida.enviadas[-1][0])


class TestCriterio3(unittest.TestCase):
    """O toque em `confirm:{cart_id}` em modo degradado cria **um** pedido."""

    def test_a_confirmacao_degradada_cria_um_pedido_e_nao_cita_numeros(self) -> None:
        det, _, _ = detector()
        conversa = _ConversaDegradada(degradacao=det)
        # **O carrinho constrói-se com o modo normal e só depois se degrada**, e
        # a ordem é a leitura do critério 2: o modo determinístico **não**
        # constrói carrinhos — serve o toque num que já existe («referência de
        # pagamento já emitida», «confirmação em modo degradado»). Um ensaio que
        # degradasse antes do primeiro turno media o menu, não a confirmação.
        primeiro = conversa.turno("quero comprar uma camisa azul")
        _abrir_o_disjuntor(det)
        carrinho = primeiro.get("cart")
        self.assertIsNotNone(carrinho, "o primeiro turno nao deu carrinho")
        antes = len(conversa.backend.encomendas)
        segundo = conversa.turno(f"confirm:{carrinho['cart_id']}", tipo="interactive")
        self.assertTrue(segundo.get("degradado"), "o segundo turno nao correu degradado")
        self.assertEqual(
            len(conversa.backend.encomendas) - antes, 1, "nao criou exactamente um pedido"
        )
        self.assertEqual(segundo["stage"], "awaiting_payment")
        self.assertTrue(segundo["draft"]["ok"], "a resposta nao passou o validador")
        # **O nome deste ensaio dizia «cita por fact» e ele não o media** — achado
        # C8. Mede-se o que é verdade, e é menos do que o critério 3 pede: a
        # resposta **não cita número nenhum**. O `total` do carrinho é um *fact*
        # do turno **anterior** e os *facts* são só do turno (§5.3), pelo que não
        # há o que citar; e a referência tem dígitos e nenhum dos cinco blocos do
        # §9.1 a leva — a dívida 124, credor KAM-032. O critério 3 fica
        # `parcial` na secção de verificação por esta metade.
        texto = segundo["draft"]["texto"]
        self.assertIn(nos_mod.MSG_PEDIDO_REGISTADO, texto)
        self.assertNotRegex(texto, r"\d", "citou um número sem *fact* deste turno")

    def test_dois_toques_degradados_nao_criam_dois_pedidos(self) -> None:
        det, _, _ = detector()
        conversa = _ConversaDegradada(degradacao=det)
        primeiro = conversa.turno("quero comprar uma camisa azul")
        _abrir_o_disjuntor(det)
        carrinho = primeiro["cart"]
        antes = len(conversa.backend.encomendas)
        conversa.turno(f"confirm:{carrinho['cart_id']}", tipo="interactive")
        conversa.turno(f"confirm:{carrinho['cart_id']}", tipo="interactive")
        self.assertEqual(len(conversa.backend.encomendas) - antes, 1)


class TestCriterio5(unittest.TestCase):
    """O validador aplica-se também aqui: nada sai sem passar pelo `validate`."""

    def test_o_menu_atravessa_o_validate_e_nao_a_aresta_34(self) -> None:
        det, _, _ = detector()
        _abrir_o_disjuntor(det)
        grafo, _, _, saida, _ = montar(degradacao=det)
        final = correr(grafo, estado_de("bom dia", tenant_id=TENANT))
        rascunho = final["draft"]
        self.assertTrue(rascunho["ok"])
        self.assertEqual(rascunho["erros"], ())
        # O `citation_retries` só sobe quando o `validate` corre: é a prova de
        # que o menu passou por ele e não pela aresta 34.
        self.assertEqual(final["citation_retries"], 0)
        self.assertEqual(rascunho["botoes"], txt.OPCOES)

    def test_o_no_do_menu_nao_devolve_texto_pronto(self) -> None:
        """Se devolvesse `texto`, o `send` enviava-o sem o `validate` o ver."""
        no = nos_deg.degraded_menu(montar()[1])
        delta = asyncio.run(no({"intent": "outro", "messages": []}))
        self.assertIn("blocos", delta["draft"])
        self.assertNotIn("texto", delta["draft"])


class TestCriterio7(unittest.TestCase):
    """Ao recuperar, o turno seguinte é normal — e nada antigo é reenviado."""

    def test_o_turno_seguinte_volta_ao_modo_normal(self) -> None:
        det, _, _ = detector()
        classificador = LlmQueRecupera(falhas=1)
        conversa = _ConversaDegradada(classificador=classificador, degradacao=det)
        primeiro = conversa.turno("bom dia")
        self.assertEqual(primeiro["degradado"], {"motivo": MOTIVO_TIMEOUT})
        segundo = conversa.turno("boa tarde")
        self.assertIsNone(segundo["degradado"], "o turno seguinte ficou degradado")
        self.assertEqual(classificador.chamadas, 2)

    def test_o_degradado_e_do_turno_e_reinicia_se_no_ingest(self) -> None:
        self.assertIn("degradado", CAMPOS_DO_TURNO)
        self.assertIsNone(CAMPOS_DO_TURNO["degradado"])

    def test_o_estado_inicial_poe_o_degradado_a_none(self) -> None:
        from apoio import invocacao_crua
        from kamba_agr.contexto import ler_invocacao

        inicial = estado_inicial(ler_invocacao(invocacao_crua()))
        self.assertIsNone(inicial["degradado"])

    def test_o_rascunho_do_turno_degradado_nao_e_reenviado_no_seguinte(self) -> None:
        """A metade da janela de 24 h que vive aqui.

        «Ao recuperar, não se reenviam respostas antigas fora da janela» (§14).
        O que o AGR garante é que **não há resposta antiga para reenviar**: o
        `draft` é do turno e o `ingest` reinicia-o. Quem impõe a janela é o
        Outbound (KAM-015), e isso fica dito na secção de verificação.
        """
        det, _, _ = detector()
        classificador = LlmQueRecupera(falhas=1)
        conversa = _ConversaDegradada(classificador=classificador, degradacao=det)
        conversa.turno("bom dia")
        primeira = list(conversa.saida.enviadas)
        self.assertEqual(len(primeira), 1)
        segundo = conversa.turno("qual o horario da loja?")
        self.assertEqual(len(conversa.saida.enviadas), 2, "reenviou ou nao respondeu")
        self.assertNotEqual(
            conversa.saida.enviadas[1][1],
            primeira[0][1],
            "a chave de idempotencia repetiu-se entre turnos",
        )
        self.assertNotIn(txt.MSG_MENU, conversa.saida.enviadas[1][0])


class TestCriterio8(unittest.TestCase):
    """O tenant no tecto com a fila acima do limiar corre degradado."""

    def test_a_contrapressao_move_o_turno_para_o_modo_deterministico(self) -> None:
        admissao = Admissao(tectos=Tectos(tecto_por_tenant=3, limiar_de_contrapressao=10))
        admissao._em_curso[TENANT] = 3  # noqa: SLF001
        admissao._a_espera = 10  # noqa: SLF001
        det, metricas, _ = detector(admissao=admissao)
        classificador = LlmQueFalha(TempoEsgotado("nunca chamado", "router"))
        grafo, _, _, saida, _ = montar(classificador=classificador, degradacao=det)
        final = correr(grafo, estado_de("bom dia", tenant_id=TENANT))
        self.assertEqual(final["degradado"], {"motivo": MOTIVO_CONTRAPRESSAO})
        self.assertEqual(classificador.chamadas, 0, "foi ao modelo em contrapressao")
        self.assertEqual(len(saida.enviadas), 1)
        self.assertIn(
            f'{METRICA_DEGRADADOS}{{motivo="{MOTIVO_CONTRAPRESSAO}"}} 1',
            metricas.exposicao(),
        )


# ------------------------------------------------- a interaccao com o concierge


class TestDegradadoComConcierge(unittest.TestCase):
    """**A hipótese do ticket, medida.** Os dois em vigor ao mesmo tempo.

    O KAM-037 foi escrito antes do KAM-114 e nenhum dos dois diz o que acontece
    com o LLM em baixo **e** a política de concierge ligada. A leitura
    implementada é a primeira das três: **a resposta determinística também vai a
    aprovação**. As outras duas — o modo degradado passa à frente do concierge, e
    o concierge fica suspenso enquanto houver degradação — retiravam uma
    barreira, e a barreira do KAM-114 é «sem decisão humana não sai mensagem».

    A decisão está devolvida ao fundador na secção de verificação do bloco e no
    corpo do PR.
    """

    def _montar(self, politica_activa: bool = True):
        det, _, _ = detector()
        _abrir_o_disjuntor(det)
        rascunho = RascunhoDeEnsaio()
        politica = PoliticaFixa(activa=politica_activa)
        grafo, deps, backend, saida, ligacao = montar(
            degradacao=det,
            concierge=politica,
            rascunho=rascunho,
            checkpointer=InMemorySaver(),
        )
        return grafo, saida, rascunho, politica

    def test_o_menu_degradado_vai_a_aprovacao_e_nao_sai_ao_cliente(self) -> None:
        grafo, saida, rascunho, politica = self._montar()
        estado = estado_de("bom dia", tenant_id=TENANT, contact_id=CONTACTO)
        asyncio.run(
            grafo.ainvoke(
                estado, {"configurable": {"thread_id": f"{TENANT}:{CONTACTO}"}}
            )
        )
        self.assertEqual(
            saida.enviadas, [], "a resposta deterministica saiu sem aprovacao humana"
        )
        self.assertEqual(len(rascunho.abertos), 1, "nao abriu rascunho de aprovacao")
        self.assertEqual(politica.leituras, [TENANT])
        # O rascunho que o operador vê é o menu, e leva o `graph_version` novo.
        self.assertIn(txt.MSG_MENU, rascunho.abertos[0]["texto"])
        self.assertEqual(rascunho.abertos[0]["graph_version"], tabela.VERSAO_DO_GRAFO)

    def test_sem_a_politica_o_menu_degradado_sai_no_mesmo_turno(self) -> None:
        """É o caso de todos os *tenants* fora do Piloto concierge.

        E é **com a política desligada** que o critério 1 se mede: «≤ 1 turno»
        é a resposta a chegar ao cliente, e com o concierge ligado ela espera
        por um humano — por desenho do KAM-114, não por falha deste modo.
        """
        grafo, saida, rascunho, _ = self._montar(politica_activa=False)
        estado = estado_de("bom dia", tenant_id=TENANT, contact_id=CONTACTO)
        asyncio.run(
            grafo.ainvoke(
                estado, {"configurable": {"thread_id": f"{TENANT}:{CONTACTO}"}}
            )
        )
        self.assertEqual(len(saida.enviadas), 1)
        self.assertEqual(rascunho.abertos, [])


# ------------------------------------------------------------- a omissao segura


class TestSemDetector(unittest.TestCase):
    """Sem detector ligado, o grafo é o que o KAM-031 e o KAM-114 entregaram."""

    def test_a_omissao_e_a_classe_sem_degradacao(self) -> None:
        _, deps, _, _, _ = montar()
        self.assertIsInstance(deps.degradacao, SemDegradacao)

    def test_sem_detector_um_turno_normal_nao_degrada(self) -> None:
        grafo, _, _, saida, _ = montar()
        final = correr(grafo, estado_de("bom dia", tenant_id=TENANT))
        self.assertIsNone(final["degradado"])
        self.assertEqual(len(saida.enviadas), 1)

    def test_sem_detector_um_erro_de_llm_nao_e_apanhado_em_silencio(self) -> None:
        """A `SemDegradacao` classifica mas **não** decide: o turno degrada.

        É a direcção segura de errar: o lado errado aqui é não degradar, porque
        é um cliente sem resposta.
        """
        classificador = LlmQueFalha(TempoEsgotado("tempo", "router"))
        grafo, _, _, saida, _ = montar(classificador=classificador)
        final = correr(grafo, estado_de("bom dia", tenant_id=TENANT))
        self.assertEqual(final["degradado"], {"motivo": MOTIVO_TIMEOUT})
        self.assertEqual(len(saida.enviadas), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
