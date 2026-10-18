"""Os `enum` dos contratos contra os domínios do dicionário (KAM-159).

O critério pede «uma *fixture* negativa por direcção». São as duas primeiras
classes — e são o que importa, porque a verificação existe por causa de um
defeito que esteve dois tickets de pé sem nenhum gate o dizer.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from contract_diff import dominios

ROOT = Path(__file__).resolve().parents[3]


def _raiz_com_copia() -> Path:
    """Uma cópia mínima do repositório: o dicionário e dois contratos."""
    pasta = Path(tempfile.mkdtemp())
    (pasta / "canon").mkdir()
    shutil.copy(ROOT / "canon" / "dicionario.yaml", pasta / "canon" / "dicionario.yaml")
    destino = pasta / "contratos" / "eventos"
    for tipo in ("order.created", "consent.recorded"):
        (destino / tipo).mkdir(parents=True)
        for ficheiro in (ROOT / "contratos" / "eventos" / tipo).iterdir():
            shutil.copy(ficheiro, destino / tipo / ficheiro.name)
    return pasta


class TestOContratoPrometeOQueOCanonNaoDeclara(unittest.TestCase):
    """Primeira direcção: um valor no `enum` que o dicionário não tem."""

    def test_um_valor_inventado_no_enum_falha(self) -> None:
        raiz = _raiz_com_copia()
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        alvo = raiz / "contratos" / "eventos" / "order.created" / "v2.schema.json"
        documento = json.loads(alvo.read_text(encoding="utf-8"))
        documento["properties"]["finalidades"]["items"]["enum"].append("inventada")
        alvo.write_text(json.dumps(documento, indent=2), encoding="utf-8")

        achados = dominios.verificar(raiz)
        self.assertTrue(achados)
        texto = "\n".join(str(a) for a in achados)
        self.assertIn("inventada", texto)
        self.assertIn("promete o que o canon nao declara", texto)

    def test_vale_para_todas_as_versoes_e_nao_so_para_a_ultima(self) -> None:
        """Um `v1` congelado não pode prometer o que o canon não declara.

        A regra não é simétrica — ver a classe seguinte —, e é aqui que a
        assimetria tem de parar: congelado não quer dizer dispensado.
        """
        raiz = _raiz_com_copia()
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        alvo = raiz / "contratos" / "eventos" / "order.created" / "v1.schema.json"
        documento = json.loads(alvo.read_text(encoding="utf-8"))
        documento["properties"]["finalidades"]["items"]["enum"].append("inventada")
        alvo.write_text(json.dumps(documento, indent=2), encoding="utf-8")

        texto = "\n".join(str(a) for a in dominios.verificar(raiz))
        self.assertIn("v1.schema.json", texto)
        self.assertIn("inventada", texto)


class TestOCanonDeclaraOQueNinguemConsegueEmitir(unittest.TestCase):
    """Segunda direcção, e o defeito original: um valor no dicionário que a
    última versão do contrato não tem."""

    def test_um_valor_que_falta_na_ultima_versao_falha(self) -> None:
        raiz = _raiz_com_copia()
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        alvo = raiz / "contratos" / "eventos" / "order.created" / "v2.schema.json"
        documento = json.loads(alvo.read_text(encoding="utf-8"))
        valores = documento["properties"]["finalidades"]["items"]["enum"]
        documento["properties"]["finalidades"]["items"]["enum"] = [
            v for v in valores if v != "partilha_estafeta"
        ]
        alvo.write_text(json.dumps(documento, indent=2), encoding="utf-8")

        texto = "\n".join(str(a) for a in dominios.verificar(raiz))
        self.assertIn("partilha_estafeta", texto)
        self.assertIn("ninguem consegue emitir", texto)

    def test_uma_versao_antiga_a_quem_falta_NAO_falha(self) -> None:
        """O §6.6: «quem quer quebrar escreve `v<N+1>` e deixa o `v<N>` como
        estava». Exigir que uma `v1` cubra um domínio que cresceu depois dela
        seria exigir que se alterasse um contrato fundido — o contrário do que
        este gate existe para impedir.

        **É o caso real**: hoje as 38 `v1` não têm as duas finalidades novas, e
        o gate está verde.
        """
        raiz = _raiz_com_copia()
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        v1 = raiz / "contratos" / "eventos" / "order.created" / "v1.schema.json"
        documento = json.loads(v1.read_text(encoding="utf-8"))
        em_falta = set(
            documento["properties"]["finalidades"]["items"]["enum"]
        )
        self.assertNotIn("partilha_estafeta", em_falta, "a fixture perdeu o sentido")
        self.assertEqual(dominios.verificar(raiz), [])


class TestSobreORepositorioReal(unittest.TestCase):
    def test_conforme(self) -> None:
        self.assertEqual([str(a) for a in dominios.verificar(ROOT)], [])

    def test_o_dominio_vigiado_existe(self) -> None:
        """Um par vigiado cujo domínio desapareça do dicionário tem de falhar,
        e não passar em silêncio por não encontrar nada que comparar."""
        canonicos = dominios._dominios(ROOT)
        for vigiado in dominios.DOMINIOS_VIGIADOS:
            with self.subTest(dominio=vigiado.dominio):
                self.assertIn(vigiado.dominio, canonicos)

    def test_cada_par_vigiado_bate_em_pelo_menos_um_contrato(self) -> None:
        """Um caminho que não bate em nada não verifica nada, e a verificação
        continuava verde. É a forma mais silenciosa de um gate morrer."""
        from contract_diff import catalogo

        contratos = catalogo.todos(ROOT)
        for vigiado in dominios.DOMINIOS_VIGIADOS:
            with self.subTest(caminho=vigiado.caminho):
                bateu = [
                    c for c in contratos
                    if dominios._enum_em(c.documento, vigiado.caminho) is not None
                ]
                self.assertTrue(bateu, f"{vigiado.caminho} nao bate em contrato nenhum")


class TestFailClosed(unittest.TestCase):
    """«Uma verificação que passa por não ter conseguido ler nada é um gate que
    mente» — a regra que o gate 11 já aplica à OSV."""

    def test_sem_dicionario_levanta(self) -> None:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        with self.assertRaises(dominios.DicionarioAusente):
            dominios.verificar(pasta)

    def test_dicionario_sem_dominios_levanta(self) -> None:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        (pasta / "canon").mkdir()
        (pasta / "canon" / "dicionario.yaml").write_text(
            "version: 1\ndominios: []\n", encoding="utf-8"
        )
        with self.assertRaises(dominios.DicionarioAusente):
            dominios.verificar(pasta)

    def test_sem_contratos_e_achado_e_nao_silencio(self) -> None:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        (pasta / "canon").mkdir()
        shutil.copy(ROOT / "canon" / "dicionario.yaml", pasta / "canon" / "dicionario.yaml")
        achados = dominios.verificar(pasta)
        self.assertTrue(achados)
        self.assertIn("sem ler nada", "\n".join(str(a) for a in achados))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
