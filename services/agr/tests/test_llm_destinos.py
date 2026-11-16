"""O adaptador da porta de destinos do AGR (KAM-069, sobre o KAM-030).

**Uma coisa so se prova aqui, e e a que nenhum outro ficheiro prova: a
traducao.**

A `PortaSobreDestinos` do `kamba_core.destinos` levanta `TransferenciaNegada`,
que **nao** e um `ErroDeLlm`. O `ClienteDeLlm.chamar` apanha `ErroDeLlm` e so:
uma `TransferenciaNegada` a subir por ali escapava ao `except`, nao contava a
metrica `agr_llm_destino_negado_total`, nao gravava a linha `destino_negado` em
`dat.llm_call_log` e **nao degradava** — o turno rebentava. Nada sairia de
Angola, pelo que a propriedade de seguranca mantinha-se; o que se perdia era
tudo o que o criterio 5 do KAM-030 fecha.

A regra da porta — a precedencia, a conjuncao, a falha fechada, o TTL — nao se
prova aqui: prova-se em `libs/py-core/tests/test_destinos.py`, sem base e sem
AGR. Repeti-la era medir a mesma coisa em dois sitios e deixar os dois a
envelhecer.
"""

from __future__ import annotations

import unittest

from kamba_core.destinos import FINALIDADES as FINALIDADES_DO_NUCLEO
from kamba_core.destinos import PortaSobreDestinos, TransferenciaNegada
from kamba_agr.llm import destinos as destinos_mod
from kamba_agr.llm.erros import DestinoNegado, ErroDeLlm

TENANT = "11111111-1111-4111-8111-111111111111"

AUTORIZADA = {
    "especifica": False,
    "status": "autorizado",
    "tem_apd_ref": True,
    "country": "US",
}
PENDENTE = {
    "especifica": False,
    "status": "pendente",
    "tem_apd_ref": False,
    "country": "US",
}


def _porta(linhas) -> destinos_mod.PortaDoNucleo:
    return destinos_mod.PortaDoNucleo(
        PortaSobreDestinos(lambda _t, _f, _p: list(linhas))
    )


class TestArrancar(unittest.TestCase):
    def test_sem_ligacao_devolve_a_porta_que_nega_tudo(self) -> None:
        """A ausencia de base **nao** afrouxa o *gate*: da a porta mais restritiva.

        E a razao de o argumento ser opcional: um `arrancar` que exigisse a
        ligacao obrigava quem nao a tem a passar `None` e a verificar o
        resultado, e o caminho natural de quem o fizesse era passar uma porta
        que autoriza.
        """
        for ambiente in (
            destinos_mod.AMBIENTE_PROD,
            destinos_mod.AMBIENTE_STAGING,
            destinos_mod.AMBIENTE_DEV,
        ):
            with self.subTest(ambiente=ambiente):
                porta = destinos_mod.arrancar(ambiente)
                self.assertIsInstance(porta, destinos_mod.NegaTudoAteKam069)

    def test_com_ligacao_devolve_a_porta_sobre_a_tabela(self) -> None:
        porta = destinos_mod.arrancar(destinos_mod.AMBIENTE_PROD, lambda: None)
        self.assertIsInstance(porta, destinos_mod.PortaDoNucleo)
        self.assertEqual(porta.nome, "tenant-destinations")

    def test_as_duas_portas_satisfazem_o_protocolo(self) -> None:
        """O `cliente.py` nao muda com a troca, e e isto que o afirma."""
        self.assertIsInstance(
            destinos_mod.arrancar(destinos_mod.AMBIENTE_DEV),
            destinos_mod.PortaDeDestinos,
        )
        self.assertIsInstance(
            destinos_mod.arrancar(destinos_mod.AMBIENTE_DEV, lambda: None),
            destinos_mod.PortaDeDestinos,
        )


class TestTraducaoDoErro(unittest.TestCase):
    def test_uma_recusa_sai_como_destino_negado(self) -> None:
        with self.assertRaises(DestinoNegado) as apanhado:
            _porta([PENDENTE]).autorizar(TENANT, "openai", "conversa")
        # E `DestinoNegado` **e** `ErroDeLlm`: e esta a cadeia de heranca que o
        # `except ErroDeLlm` do `cliente.py` apanha.
        self.assertIsInstance(apanhado.exception, ErroDeLlm)
        self.assertNotIsInstance(apanhado.exception, TransferenciaNegada)

    def test_a_mensagem_passa_inteira(self) -> None:
        """Ela nomeia o fornecedor, o pais e o estado — e isso e o diagnostico.

        As cinco maneiras de negar dao textos diferentes, e um adaptador que
        substituisse a mensagem por uma sua tornava-as indistinguiveis no
        registo.
        """
        with self.assertRaises(DestinoNegado) as apanhado:
            _porta([PENDENTE]).autorizar(TENANT, "openai", "conversa")
        mensagem = str(apanhado.exception)
        self.assertIn("openai", mensagem)
        self.assertIn("`US` esta `pendente`", mensagem)
        self.assertIn("ADR-008", mensagem)

    def test_um_destino_autorizado_passa_sem_levantar(self) -> None:
        """O canario: um adaptador que levantasse sempre passava os dois acima."""
        _porta([AUTORIZADA]).autorizar(TENANT, "openai", "conversa")

    def test_a_cache_fica_ao_alcance_de_quem_revoga(self) -> None:
        porta = _porta([AUTORIZADA])
        porta.autorizar(TENANT, "openai", "conversa")
        self.assertEqual(porta.cache.tamanho, 1)
        porta.cache.invalidar(TENANT)
        self.assertEqual(porta.cache.tamanho, 0)


class TestFinalidades(unittest.TestCase):
    def test_as_tres_deste_servico_sao_tres_das_do_nucleo(self) -> None:
        """O dominio e da coluna e nao do servico (dicionario §3.49).

        Deste lado interessam tres; a coluna tem catorze, porque o *gate* corre em
        sete pontos e so um e o *gateway* de modelos. **Subconjunto proprio**, e
        afirma-se nos dois sentidos: um valor daqui que a coluna nao conheca
        nunca teria linha a consultar, e a coluna ter mais do que estes tres e o
        desenho.
        """
        self.assertEqual(len(destinos_mod.FINALIDADES), 3)
        self.assertTrue(set(destinos_mod.FINALIDADES) < set(FINALIDADES_DO_NUCLEO))

    def test_cada_papel_tem_finalidade_e_um_papel_estranho_nao(self) -> None:
        for papel in ("router", "chat", "vision", "embed"):
            with self.subTest(papel=papel):
                self.assertIn(
                    destinos_mod.finalidade_de(papel), destinos_mod.FINALIDADES
                )
        with self.assertRaises(DestinoNegado):
            destinos_mod.finalidade_de("papel_que_nao_existe")
        # O `screening` (KAM-192) e um papel do cliente sem finalidade: nega.
        with self.assertRaises(DestinoNegado):
            destinos_mod.finalidade_de("screening")


if __name__ == "__main__":
    unittest.main()
