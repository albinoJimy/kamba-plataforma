"""A entrada da foto no arranque do AGR (KAM-231; decisao do fundador P4, opcao A).

Em `staging` e `prod` o AGR nao arranca sem os segredos e a configuracao do
STO; em `dev` arranca com a foto por ligar e di-lo no registo. As portas da foto
ligam-se tarde (`EntradaDaFoto`), e ate la fecham.
"""

from __future__ import annotations

import json
import unittest
from decimal import Decimal

import test_arranque
from test_arranque import AMBIENTE_BASE

from kamba_agr.catalogo.entrada import SEGREDOS_DO_STO, EntradaDaFoto
from kamba_agr.catalogo.fonte import FonteDoMed
from kamba_agr.catalogo.montagem import MODULO_DA_FOTO, EnhancePorEntitlement, FotoPorLigarError
from kamba_core.catalogo.pipeline import ErroDaVisao, RespostaDaVisao
from kamba_core.storage import criar_storage_fake

STO = {
    "KAMBA_STORAGE_ENDPOINT": "http://sto.invalido:8333",
    "KAMBA_STORAGE_BUCKET": "kamba-teste",
    "KAMBA_STORAGE_REGION": "af-south-1",
    "KAMBA_STORAGE_DESTINO_COUNTRY": "AO",
    "KAMBA_STORAGE_DESTINO_PROVIDER": "seaweedfs",
}
SEGREDOS_STO = {f"KAMBA_SECRET_{s.upper()}": "valor-de-ensaio" for s in SEGREDOS_DO_STO}
#: KAM-246 (Q3 = A): a chave da ligacao de descarga do painel e obrigatoria em
#: `staging` e `prod`, como os do STO; sem ela o AGR nao arranca.
SEGREDO_DA_LIGACAO = {"KAMBA_SECRET_CHAVE_DA_LIGACAO_DE_DESCARGA": "l" * 32}


class _Visao:
    fornecedores = ("anthropic",)

    def extrair(self, tenant_id: str, imagem: bytes, *, tecto_s: float | None = None) -> RespostaDaVisao:
        return RespostaDaVisao(texto="{}", custo_usd=Decimal("0.001"))


class _Destinos:
    def __init__(self) -> None:
        self.vistos: list[tuple[str, str, str]] = []

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
        self.vistos.append((tenant_id, fornecedor, finalidade))


class TestAsPortasTardias(unittest.TestCase):
    def test_por_ligar_fecham(self) -> None:
        e = EntradaDaFoto()
        with self.assertRaises(FotoPorLigarError):
            e.storage.get  # noqa: B018
        self.assertEqual(e.visao.fornecedores, ())
        with self.assertRaises(ErroDaVisao):
            e.visao.extrair("t", b"x")
        with self.assertRaises(PermissionError):
            e.destinos.autorizar("t", "anthropic", "visao")

    def test_ligadas_delegam(self) -> None:
        e = EntradaDaFoto()
        sto = criar_storage_fake().storage
        destinos = _Destinos()
        e.ligar(storage=sto, visao=_Visao(), destinos=destinos)
        self.assertEqual(e.storage.get, sto.get)
        self.assertEqual(e.visao.fornecedores, ("anthropic",))
        self.assertEqual(e.visao.extrair("t", b"x").custo_usd, Decimal("0.001"))
        e.destinos.autorizar("t", "anthropic", "visao")
        self.assertEqual(destinos.vistos, [("t", "anthropic", "visao")])
        fonte = e.fonte_sobre("ligacao")
        self.assertIsInstance(fonte, FonteDoMed)
        self.assertEqual(fonte.ligacao, "ligacao")


class TestAOfertaDeMelhorarFoto(unittest.TestCase):
    """Criterio 4: a oferta so com o entitlement `foto` activo, e nunca um erro."""

    def test_so_com_o_foto_activo(self) -> None:
        vistos: list[tuple[str, str]] = []

        class _E:
            def __init__(self, ativo: bool) -> None:
                self.ativo = ativo

        def ler(activos: set[str]):  # type: ignore[no-untyped-def]
            def leitor(tenant: str, modulo: str) -> _E:
                vistos.append((tenant, modulo))
                return _E(tenant in activos)

            return leitor

        porta = EnhancePorEntitlement(ler({"A"}))
        self.assertTrue(porta.disponivel("A"))
        self.assertFalse(porta.disponivel("B"))
        self.assertEqual(vistos, [("A", MODULO_DA_FOTO), ("B", MODULO_DA_FOTO)])

    def test_uma_leitura_que_falha_e_sem_oferta(self) -> None:
        def falha(_t: str, _m: str) -> None:
            raise RuntimeError("base em baixo")

        self.assertFalse(EnhancePorEntitlement(falha).disponivel("A"))

    def test_o_processo_liga_a_do_entitlement(self) -> None:
        from kamba_agr import __main__ as principal

        portas = principal._portas_da_foto(EntradaDaFoto(), "dev")
        self.assertIsInstance(portas["enhance"], EnhancePorEntitlement)
        self.assertEqual(portas["ambiente"], "dev")


class TestOArranque(unittest.TestCase):
    # O arnes do `test_arranque`, sem herdar (e correr outra vez) os ensaios dele.
    setUp = test_arranque.TestArranque.setUp
    _correr = test_arranque.TestArranque._correr

    def _erro(self) -> str:
        for linha in reversed(self.saida.getvalue().splitlines()):
            dados = json.loads(linha)
            if dados.get("level") == "error":
                return str(dados.get("error_code"))
        return ""

    def _linha(self, outcome: str) -> dict[str, object] | None:
        for linha in self.saida.getvalue().splitlines():
            dados = json.loads(linha)
            if dados.get("outcome") == outcome:
                return dados
        return None

    def test_em_staging_sem_os_segredos_do_sto_nao_arranca(self) -> None:
        codigo, correr = self._correr({**AMBIENTE_BASE, **STO, "KAMBA_ENV": "staging"})
        self.assertEqual(codigo, 2)
        correr.assert_not_called()
        self.assertTrue(self._erro().startswith("cofre_indisponivel"), self._erro())

    def test_em_staging_sem_a_configuracao_do_sto_nao_arranca(self) -> None:
        codigo, correr = self._correr({**AMBIENTE_BASE, **SEGREDOS_STO, **SEGREDO_DA_LIGACAO, "KAMBA_ENV": "staging"})
        self.assertEqual(codigo, 2)
        correr.assert_not_called()
        self.assertTrue(self._erro().startswith("sto_indisponivel"), self._erro())

    def test_em_staging_com_o_sto_arranca_com_a_foto_ligada(self) -> None:
        codigo, correr = self._correr(
            {**AMBIENTE_BASE, **STO, **SEGREDOS_STO, **SEGREDO_DA_LIGACAO, "KAMBA_ENV": "staging"}
        )
        self.assertEqual(codigo, 0, self.saida.getvalue()[-2000:])
        correr.assert_called_once()
        self.assertEqual((self._linha("catalogo_foto") or {}).get("error_code"), "foto_ligada")

    def test_kam_246_em_staging_sem_a_chave_da_ligacao_nao_arranca(self) -> None:
        codigo, correr = self._correr({**AMBIENTE_BASE, **STO, **SEGREDOS_STO, "KAMBA_ENV": "staging"})
        self.assertEqual(codigo, 2)
        correr.assert_not_called()
        self.assertTrue(self._erro().startswith("cofre_indisponivel"), self._erro())

    def test_em_dev_sem_sto_arranca_e_diz_que_a_foto_esta_por_ligar(self) -> None:
        codigo, correr = self._correr(dict(AMBIENTE_BASE))
        self.assertEqual(codigo, 0)
        correr.assert_called_once()
        self.assertEqual((self._linha("catalogo_foto") or {}).get("error_code"), "foto_por_ligar_sem_sto")


if __name__ == "__main__":
    unittest.main()
