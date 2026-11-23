"""O prazo e a ligacao no pipeline do KAM-049 (KAM-244).

Achados 4 e 5 da revisao adversarial do KAM-231: o `create_product_draft` de uma
foto prendia a tomada da ToolLayer durante a visao e o screening, e os tectos
de dentro (visao 18 s, screening 20 s, Registo 5 s) somavam mais do que os 25 s
da tool, sem o `Pedido.prazo` descer ao pipeline.

Sem rede e sem relogio de parede: as portas sao os duplos do KAM-049, que
«esperam» num `RelogioFake` o que a demora delas pede, cortada ao `tecto_s` que
receberam, e levantam se a demora passar dele. E o contrato que os adaptadores
do AGR cumprem (`visao.py`, `tls/screening.py`, `tls/registo_com.py`).
"""

from __future__ import annotations

import itertools
import unittest
from dataclasses import replace
from typing import Any

from catalogo_apoio import A, RelogioFake, confirmacao, montar, responder

from kamba_core.catalogo import estados
from kamba_core.catalogo.pipeline import (
    RESERVA_DAS_ESCRITAS_MS,
    RESERVA_DEPOIS_DA_VISAO_MS,
    RESERVA_DEPOIS_DO_SCREENING_MS,
    REGRAS_RETOMAVEIS,
)
from kamba_core.catalogo.repositorio import RepositorioEmMemoria

#: O tecto do `create_product_draft` de uma foto (`TECTOS_POR_TOOL`, P3-A).
TECTO_S = 25.0


def _com_prazo(m: Any, relogio: RelogioFake, prazo_s: float = TECTO_S, **extra: Any) -> Any:
    for porta in (m.visao, m.screening, m.registo):
        porta.relogio = relogio
    m.servico = replace(m.servico, prazo=relogio.agora + prazo_s, relogio=relogio, **extra)
    return m


def _ate_ao_rascunho(m: Any, ingestao_id: str) -> Any:
    for respostas in (
        {"preco_tipo": "é fixo"},
        {"preco": "12 mil"},
        {"stock_modo": "garantido"},
        {"stock": "5"},
        {"entrega": "entrega em Luanda"},
    ):
        r = responder(m.servico, A, ingestao_id, respostas)
    return r


class TestSemPrazo(unittest.TestCase):
    def test_sem_prazo_as_portas_usam_o_tecto_delas(self) -> None:
        """A forma de antes: quem nao da prazo nao muda nada (`retomar`, ensaios)."""
        m = montar()
        r = m.servico.receber(A, "m1")
        r = _ate_ao_rascunho(m, r.ingestao.id)
        self.assertEqual(r.estado, estados.RASCUNHO)
        self.assertEqual(m.visao.tectos, [None])
        self.assertTrue(m.screening.tectos)
        self.assertEqual(set(m.screening.tectos), {None})
        self.assertEqual(m.registo.tectos, [None])


class TestOOrcamento(unittest.TestCase):
    def test_cada_etapa_recebe_o_que_sobra_menos_as_seguintes(self) -> None:
        relogio = RelogioFake()
        m = _com_prazo(montar(), relogio)
        r = m.servico.receber(A, "m1")
        self.assertEqual(r.estado, estados.A_PERGUNTAR)
        self.assertEqual(m.visao.tectos, [TECTO_S - RESERVA_DEPOIS_DA_VISAO_MS / 1000])
        self.assertEqual(m.screening.tectos, [TECTO_S - RESERVA_DEPOIS_DO_SCREENING_MS / 1000])

    def test_o_registo_recebe_o_que_sobra_menos_as_escritas(self) -> None:
        relogio = RelogioFake()
        m = montar()
        r = _ate_ao_rascunho(m, m.servico.receber(A, "m1").ingestao.id)
        self.assertEqual(r.estado, estados.RASCUNHO)
        # Uma correccao do dono, com prazo: o screening e o Registo correm.
        _com_prazo(m, relogio)
        m.registo.tectos.clear()
        responder(m.servico, A, r.ingestao.id, {"cor": "verde"})
        self.assertEqual(m.registo.tectos, [TECTO_S - RESERVA_DAS_ESCRITAS_MS / 1000])

    def test_o_pior_caso_acaba_antes_do_prazo_com_a_reserva_das_escritas(self) -> None:
        """A soma no pior caso cabe nos 25 s, seja qual for a porta que se atrasa.

        Cada porta demora 0 s, metade do tecto dela, o tecto inteiro, ou para
        sempre (cortada no que recebeu). A ultima escrita acaba, no pior caso, a
        `RESERVA_DAS_ESCRITAS_MS` do prazo. O caminho vai da foto ao rascunho com
        uma correccao do dono, para que as tres portas corram na mesma invocacao.
        """
        demoras = (0.0, 7.0, 18.0, 1e9)
        for visao, screening, registo in itertools.product(demoras, demoras, (0.0, 2.5, 5.0, 1e9)):
            with self.subTest(visao=visao, screening=screening, registo=registo):
                relogio = RelogioFake()
                m = _com_prazo(montar(), relogio)
                m.visao.demora_s, m.screening.demora_s, m.registo.demora_s = visao, screening, registo
                inicio = relogio.agora
                try:
                    m.servico.receber(A, "m1")
                except TimeoutError:
                    pass  # o Registo cortado sobe: o executor do AGR trata-o
                self.assertLessEqual(relogio.agora - inicio, TECTO_S - RESERVA_DAS_ESCRITAS_MS / 1000)


class TestAdversarial(unittest.TestCase):
    """A visao e o screening nos seus tectos ao mesmo tempo."""

    def test_a_visao_e_o_screening_no_tecto_acabam_dentro_dos_vinte_e_cinco(self) -> None:
        relogio = RelogioFake()
        m = _com_prazo(montar(), relogio)
        m.visao.demora_s = 18.0  # o TECTO_DA_VISAO_S do AGR
        m.screening.demora_s = 20.0  # o TEMPO_MAXIMO_MS da ponte do COM
        inicio = relogio.agora
        r = m.servico.receber(A, "m1")
        self.assertLessEqual(relogio.agora - inicio, TECTO_S - RESERVA_DEPOIS_DO_SCREENING_MS / 1000)
        # A visao foi cortada no que sobrava; o screening nao decidiu: a
        # ingestao fica bloqueada **sem decisao**, e isso retoma-se.
        self.assertEqual(r.estado, estados.BLOQUEADA_CATEGORIA)
        self.assertIn(r.ingestao.categoria_restrita, REGRAS_RETOMAVEIS)

    def test_o_corte_do_screening_retoma_ate_ao_resumo(self) -> None:
        """Um rascunho corrigido com o screening cortado volta ao resumo pelo `retomar`."""
        m = montar()
        r = _ate_ao_rascunho(m, m.servico.receber(A, "m1").ingestao.id)
        self.assertEqual(r.estado, estados.RASCUNHO)
        relogio = RelogioFake()
        _com_prazo(m, relogio)
        m.screening.demora_s = 1e9
        cortada = responder(m.servico, A, r.ingestao.id, {"categoria": "moda"})
        self.assertEqual(cortada.estado, estados.BLOQUEADA_CATEGORIA)
        self.assertIn(cortada.ingestao.categoria_restrita, REGRAS_RETOMAVEIS)
        # O turno seguinte: prazo novo, screening a responder.
        m.screening.demora_s = 0.0
        _com_prazo(m, relogio)
        retomada = m.servico.retomar(A, r.ingestao.id)
        self.assertEqual(retomada.estado, estados.RASCUNHO)
        self.assertIn("categoria moda", retomada.resumo or "")
        publicada = m.servico.confirmar(A, r.ingestao.id, confirmacao(retomada.versao_texto or ""))
        self.assertEqual(publicada.estado, estados.PUBLICADA)

    def test_uma_decisao_restritiva_nao_e_retomavel(self) -> None:
        """O contra-exemplo: `alcool` e uma decisao, e o `retomar` nao a levanta."""
        m = montar()
        r = _ate_ao_rascunho(m, m.servico.receber(A, "m1").ingestao.id)
        bloqueada = responder(m.servico, A, r.ingestao.id, {"categoria": "cerveja"})
        self.assertEqual(bloqueada.estado, estados.BLOQUEADA_CATEGORIA)
        self.assertNotIn(bloqueada.ingestao.categoria_restrita, REGRAS_RETOMAVEIS)
        self.assertEqual(m.servico.retomar(A, r.ingestao.id).estado, estados.BLOQUEADA_CATEGORIA)


class _Repositorio(RepositorioEmMemoria):
    """O repositorio em memoria, a registar se cada operacao correu fora da ligacao."""

    def __init__(self, fora: list[bool]) -> None:
        super().__init__()
        self._fora = fora
        self.operacoes: list[tuple[str, bool]] = []

    def __getattribute__(self, nome: str) -> Any:
        valor = super().__getattribute__(nome)
        if nome in ("ler", "por_media", "inserir", "gravar", "com_phash"):
            fora, operacoes = super().__getattribute__("_fora"), super().__getattribute__("operacoes")

            def registada(*args: Any, **kwargs: Any) -> Any:
                operacoes.append((nome, fora[0]))
                return valor(*args, **kwargs)

            return registada
        return valor


class TestForaDaLigacao(unittest.TestCase):
    def test_a_visao_e_o_screening_correm_fora_e_o_repositorio_nunca(self) -> None:
        fora = [False]
        chamadas: list[str] = []

        def fora_da_ligacao(trabalho: Any) -> Any:
            fora[0] = True
            try:
                return trabalho()
            finally:
                fora[0] = False

        m = montar()
        repo = _Repositorio(fora)
        m.servico = replace(m.servico, repositorio=repo, fora_da_ligacao=fora_da_ligacao)
        visao_extrair, screening_screen = m.visao.extrair, m.screening.screen

        def visao(*args: Any, **kwargs: Any) -> Any:
            chamadas.append(f"visao:{fora[0]}")
            return visao_extrair(*args, **kwargs)

        def screen(*args: Any, **kwargs: Any) -> Any:
            chamadas.append(f"screening:{fora[0]}")
            return screening_screen(*args, **kwargs)

        m.visao.extrair = visao  # type: ignore[method-assign]
        m.screening.screen = screen  # type: ignore[method-assign]
        r = m.servico.receber(A, "m1")
        r = _ate_ao_rascunho(m, r.ingestao.id)
        m.servico.confirmar(A, r.ingestao.id, confirmacao(r.versao_texto or ""))
        self.assertEqual(chamadas[0], "visao:True")
        self.assertIn("screening:True", chamadas)
        self.assertTrue(all(c.endswith(":True") for c in chamadas), chamadas)
        self.assertTrue(repo.operacoes)
        self.assertEqual([op for op in repo.operacoes if op[1]], [])


if __name__ == "__main__":
    unittest.main()
