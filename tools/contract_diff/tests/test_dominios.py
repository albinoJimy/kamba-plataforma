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


def _versoes(raiz: Path, tipo: str) -> list[int]:
    """As versões no disco. **Lidas, e não escritas à mão no teste.**

    A primeira versão destes testes fixava `v2` como «a última». No dia em que
    nascesse uma `v3`, metade deles passaria a falhar pela premissa e não pelo
    defeito — e quem os visse apontava-os à `v3` e seguia, sem reparar que a
    *fixture* «uma por direcção» tinha deixado de provar o que diz (achado m2).
    """
    import re

    return sorted(
        int(m.group(1))
        for p in (raiz / "contratos" / "eventos" / tipo).iterdir()
        if (m := re.fullmatch(r"v([1-9][0-9]*)\.schema\.json", p.name))
    )


def _ultima(raiz: Path, tipo: str) -> int:
    return max(_versoes(raiz, tipo))


def _schema(raiz: Path, tipo: str, versao: int) -> Path:
    return raiz / "contratos" / "eventos" / tipo / f"v{versao}.schema.json"


def _mexer(caminho: Path, muda) -> None:
    documento = json.loads(caminho.read_text(encoding="utf-8"))
    muda(documento)
    caminho.write_text(json.dumps(documento, indent=2), encoding="utf-8")


class TestOContratoPrometeOQueOCanonNaoDeclara(unittest.TestCase):
    """Primeira direcção: um valor no `enum` que o dicionário não tem."""

    def test_um_valor_inventado_no_enum_falha(self) -> None:
        raiz = _raiz_com_copia()
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        alvo = _schema(raiz, "order.created", _ultima(raiz, "order.created"))
        _mexer(alvo, lambda d: d["properties"]["finalidades"]["items"]["enum"].append("inventada"))

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
        alvo = _schema(raiz, "order.created", 1)
        _mexer(alvo, lambda d: d["properties"]["finalidades"]["items"]["enum"].append("inventada"))

        texto = "\n".join(str(a) for a in dominios.verificar(raiz))
        self.assertIn("v1.schema.json", texto)
        self.assertIn("inventada", texto)


class TestOCanonDeclaraOQueNinguemConsegueEmitir(unittest.TestCase):
    """Segunda direcção, e o defeito original: um valor no dicionário que a
    última versão do contrato não tem."""

    def test_um_valor_que_falta_na_ultima_versao_falha(self) -> None:
        raiz = _raiz_com_copia()
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        alvo = _schema(raiz, "order.created", _ultima(raiz, "order.created"))

        def tirar(documento: dict) -> None:
            items = documento["properties"]["finalidades"]["items"]
            items["enum"] = [v for v in items["enum"] if v != "partilha_estafeta"]

        _mexer(alvo, tirar)
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


class TestUmContratoSemEnumNenhum(unittest.TestCase):
    """O buraco que a revisão adversarial encontrou, e que é o pior de todos.

    As duas direcções acima comparam conjuntos. Um contrato cujo caminho
    vigiado **não tenha `enum`** não tem conjunto nenhum, e a primeira versão
    desta verificação fazia `continue` em silêncio: um
    `items: {"type": "string"}` aceita qualquer cadeia como finalidade e o
    gate dizia «0 divergências». A revisão provou-o com 38 `v3` sem `enum`,
    exemplos a emitir uma finalidade inventada, e o gate 7 **e** o 3b verdes.
    """

    def test_o_envelope_sem_enum_falha(self) -> None:
        raiz = _raiz_com_copia()
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        alvo = _schema(raiz, "order.created", _ultima(raiz, "order.created"))
        _mexer(
            alvo,
            lambda d: d["properties"]["finalidades"].__setitem__("items", {"type": "string"}),
        )

        texto = "\n".join(str(a) for a in dominios.verificar(raiz))
        self.assertIn("existe sem `enum`", texto)
        self.assertIn("order.created", texto)

    def test_o_envelope_sem_enum_numa_versao_antiga_tambem_falha(self) -> None:
        """A regra do envelope é «todos», e não «o último».

        Uma `v1` publicada está congelada quanto ao **conteúdo** do domínio —
        não quanto a ter domínio. Um `v1` que perdesse o `enum` deixava de
        impor o que impunha no dia em que foi publicado.
        """
        raiz = _raiz_com_copia()
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        _mexer(
            _schema(raiz, "order.created", 1),
            lambda d: d["properties"]["finalidades"].__setitem__("items", {"type": "string"}),
        )
        texto = "\n".join(str(a) for a in dominios.verificar(raiz))
        self.assertIn("v1.schema.json", texto)
        self.assertIn("existe sem `enum`", texto)

    def test_uma_versao_nova_que_perde_o_enum_do_payload_falha(self) -> None:
        """A regra por herança: quem o teve tem de o ter na última.

        Só os dois `consent.*` têm `payload.finalidade`; exigi-lo aos outros
        36 seria falso. Mas um tipo que o teve e deixa de o ter numa versão
        nova está a abrir o campo, e a última versão é a que um produtor novo
        escreve.
        """
        raiz = _raiz_com_copia()
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        ultima = _ultima(raiz, "consent.recorded")
        origem = _schema(raiz, "consent.recorded", ultima)
        documento = json.loads(origem.read_text(encoding="utf-8"))
        documento["properties"]["versao"]["const"] = ultima + 1
        documento["properties"]["payload"]["properties"]["finalidade"] = {"type": "string"}
        _schema(raiz, "consent.recorded", ultima + 1).write_text(
            json.dumps(documento, indent=2), encoding="utf-8"
        )

        texto = "\n".join(str(a) for a in dominios.verificar(raiz))
        self.assertIn(f"v{ultima + 1}.schema.json", texto)
        self.assertIn("esvaziar o dominio", texto)

    def test_quem_nunca_teve_o_payload_nao_e_acusado(self) -> None:
        """O controlo da regra anterior: sem ele, a regra dizia «todos» e os
        36 contratos sem `payload.finalidade` ficavam vermelhos para sempre."""
        raiz = _raiz_com_copia()
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        caminho = ("properties", "payload", "properties", "finalidade")
        from contract_diff import catalogo as cat

        semelhantes = [
            c for c in cat.todos(raiz)
            if c.tipo == "order.created" and dominios._enum_em(c.documento, caminho) is not None
        ]
        self.assertEqual(semelhantes, [], "a fixture perdeu o sentido")
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


class TestOQueAVersaoNovaAcrescentaEhEmitidoPorAlgumExemplo(unittest.TestCase):
    """O que uma versão nova acrescenta ao domínio tem de aparecer num exemplo.

    O KAM-159 existe porque duas finalidades do canon eram **impossíveis de
    emitir**. Entraram com a `v2` — e os 38 `exemplo.v2.json` nasceram cópias
    dos `exemplo.json`, diferindo só no número da versão: nenhum as usava. A
    afirmação «agora emitem-se» não tinha uma única prova executável, e foi a
    revisão adversarial que o apanhou (achado m3).

    A regra não é «todos os valores do domínio num exemplo» — isso exigiria
    exemplos para finalidades que nenhum tipo de evento usa. É mais estreita e
    é a que o ticket promete: **o que a última versão acrescenta** à anterior
    é exercitado em algum sítio.
    """

    def test_cada_valor_novo_aparece_em_algum_exemplo(self) -> None:
        from contract_diff import catalogo

        canonicos = dominios._dominios(ROOT)
        contratos = catalogo.todos(ROOT)
        ultima_de: dict[str, int] = {}
        for contrato in contratos:
            ultima_de[contrato.tipo] = max(ultima_de.get(contrato.tipo, 0), contrato.versao)

        for vigiado in dominios.DOMINIOS_VIGIADOS:
            # O que a última versão tem e a primeira não — por tipo, e unido.
            novos: set[str] = set()
            for contrato in contratos:
                if contrato.versao != ultima_de[contrato.tipo]:
                    continue
                agora = dominios._enum_em(contrato.documento, vigiado.caminho)
                if agora is None:
                    continue
                antes = next(
                    (
                        dominios._enum_em(c.documento, vigiado.caminho) or []
                        for c in contratos
                        if c.tipo == contrato.tipo and c.versao == 1
                    ),
                    [],
                )
                novos |= set(agora) - set(antes)
            if not novos:
                continue
            self.assertLessEqual(novos, set(canonicos[vigiado.dominio]))
            emitidos = self._emitidos(contratos, ultima_de, vigiado)
            for valor in sorted(novos):
                with self.subTest(dominio=vigiado.dominio, valor=valor):
                    self.assertIn(
                        valor,
                        emitidos,
                        f"«{valor}» entrou no dominio e nenhum exemplo o emite: "
                        "a verificacao de exemplos valida 76 contratos e nao "
                        "exercita este valor em nenhum",
                    )

    @staticmethod
    def _emitidos(contratos, ultima_de, vigiado) -> set[str]:
        """Os valores que os exemplos da última versão realmente escrevem."""
        from contract_diff import catalogo

        # O caminho no exemplo é o do schema sem os passos de JSON Schema.
        no_exemplo = tuple(p for p in vigiado.caminho if p not in ("properties", "items"))
        vistos: set[str] = set()
        for contrato in contratos:
            if contrato.versao != ultima_de[contrato.tipo]:
                continue
            caminho = catalogo.exemplo_de(contrato)
            if caminho is None or not caminho.is_file():
                continue
            no = json.loads(caminho.read_text(encoding="utf-8"))
            for passo in no_exemplo:
                if not isinstance(no, dict) or passo not in no:
                    no = None
                    break
                no = no[passo]
            if isinstance(no, str):
                vistos.add(no)
            elif isinstance(no, list):
                vistos |= {str(v) for v in no}
        return vistos


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
