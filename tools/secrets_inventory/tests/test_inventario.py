"""Esquema e cobertura do inventario de segredos (KAM-010).

**Um caso negativo por regra.** Cada regra que o esquema impoe tem aqui um teste
que a viola e exige a mensagem certa; sem isso, uma regra que deixasse de ser
aplicada passava sem ninguem notar — que e exactamente o modo de falha que uma
verificacao de inventario existe para fechar.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from secrets_inventory.canon import componentes_do_doc_00, normalizar, segredos_do_doc_08
from secrets_inventory.inventario import carregar, cobertura, orfas, validar

RAIZ = Path(__file__).resolve().parents[3]

COMPONENTES = {"GWY", "CHR", "AGR", "TEN", "PAY", "LLM", "HND", "DAT", "GOV", "MED"}


def entrada(**sobrepor: object) -> dict[str, object]:
    """Uma entrada valida, com os campos que se quiserem sobrepostos."""
    base: dict[str, object] = {
        "id": "meta_app_secret",
        "fonte_08_5": "Meta App Secret",
        "descricao": "assina o webhook",
        "owner": "eng_canais",
        "rotacao_dias": 182,
        "rotacao_gatilho": "incidente",
        "ambientes": ["dev", "staging", "prod"],
        "obrigatorio_em": ["prod"],
        "consumidores": ["GWY"],
        "instancias": "nenhuma",
        "anel": True,
        "kid": False,
    }
    base.update(sobrepor)
    return base


def documento(**sobrepor: object) -> dict[str, object]:
    base: dict[str, object] = {
        "versao": 1,
        "ticket": "KAM-010",
        "estado": "proposta",
        "fonte": "docs/tecnica/08 §5",
        "actualizado_em": "2026-10-11",
        "estado_dos_campos": "proposta",
        "analise_raizes": ["services"],
        "analise_excluir": [{"caminho": "x", "razao": "porque"}],
        "segredos": [entrada()],
    }
    base.update(sobrepor)
    return base


class TestEsquemaAceita(unittest.TestCase):
    def test_documento_minimo_valido(self) -> None:
        inventario, erros = validar(documento(), COMPONENTES)
        self.assertEqual(erros, [])
        self.assertEqual(len(inventario.segredos), 1)
        self.assertEqual(inventario.por_id["meta_app_secret"].rotacao_dias, 182)

    def test_rotacao_por_evento_com_gatilho(self) -> None:
        _, erros = validar(
            documento(
                segredos=[
                    entrada(
                        id="meta_client_token",
                        rotacao_dias=None,
                        rotacao_gatilho="offboard_ou_expiracao",
                        instancias="tenant",
                        obrigatorio_em=[],
                    )
                ]
            ),
            COMPONENTES,
        )
        self.assertEqual(erros, [])

    def test_consumidores_vazio_com_nota(self) -> None:
        _, erros = validar(
            documento(
                segredos=[
                    entrada(consumidores=[], nota="le-o o processo de migracao, nao a app")
                ]
            ),
            COMPONENTES,
        )
        self.assertEqual(erros, [])


class TestEsquemaRecusa(unittest.TestCase):
    def _erros(self, doc: dict[str, object]) -> str:
        _, erros = validar(doc, COMPONENTES)
        self.assertTrue(erros, "esperava pelo menos um erro")
        return "\n".join(erros)

    def test_falta_chave_de_topo(self) -> None:
        doc = documento()
        del doc["fonte"]
        self.assertIn("falta a chave de topo 'fonte'", self._erros(doc))

    def test_chave_de_topo_desconhecida(self) -> None:
        self.assertIn("desconhecida: 'extra'", self._erros(documento(extra=1)))

    def test_versao_errada(self) -> None:
        self.assertIn("versao suportada e 1", self._erros(documento(versao=2)))

    def test_segredos_vazio(self) -> None:
        self.assertIn("lista nao vazia", self._erros(documento(segredos=[])))

    def test_falta_um_campo(self) -> None:
        crua = entrada()
        del crua["owner"]
        self.assertIn("falta o campo 'owner'", self._erros(documento(segredos=[crua])))

    def test_campo_desconhecido(self) -> None:
        self.assertIn(
            "campo desconhecido 'valor'",
            self._erros(documento(segredos=[entrada(valor="nunca")])),
        )

    def test_id_mal_formado(self) -> None:
        for mau in ("META_APP_SECRET", "ab", "com espaco", "meta/instancia", 7):
            with self.subTest(id=mau):
                self.assertIn(
                    "snake_case", self._erros(documento(segredos=[entrada(id=mau)]))
                )

    def test_id_repetido(self) -> None:
        self.assertIn(
            "`id` repetido", self._erros(documento(segredos=[entrada(), entrada()]))
        )

    def test_owner_fora_dos_papeis(self) -> None:
        self.assertIn(
            "fora dos papeis", self._erros(documento(segredos=[entrada(owner="joao")]))
        )

    def test_rotacao_nula_sem_gatilho(self) -> None:
        self.assertIn(
            "exige `rotacao_gatilho`",
            self._erros(
                documento(segredos=[entrada(rotacao_dias=None, rotacao_gatilho="")])
            ),
        )

    def test_rotacao_nao_positiva(self) -> None:
        for mau in (0, -1, "90", True):
            with self.subTest(dias=mau):
                self.assertIn(
                    "inteiro > 0 ou null",
                    self._erros(documento(segredos=[entrada(rotacao_dias=mau)])),
                )

    def test_ambientes_vazio(self) -> None:
        self.assertIn(
            "nao pode ser vazio",
            self._erros(documento(segredos=[entrada(ambientes=[], obrigatorio_em=[])])),
        )

    def test_ambiente_desconhecido(self) -> None:
        self.assertIn(
            "ambiente desconhecido 'producao'",
            self._erros(
                documento(segredos=[entrada(ambientes=["producao"], obrigatorio_em=[])])
            ),
        )

    def test_obrigatorio_fora_dos_ambientes(self) -> None:
        # Um segredo nao pode ser obrigatorio onde nao existe.
        self.assertIn(
            "que nao esta em `ambientes`",
            self._erros(
                documento(segredos=[entrada(ambientes=["dev"], obrigatorio_em=["prod"])])
            ),
        )

    def test_consumidor_fora_do_catalogo(self) -> None:
        self.assertIn(
            "nao e um codigo do catalogo",
            self._erros(documento(segredos=[entrada(consumidores=["XYZ"])])),
        )

    def test_consumidores_vazio_sem_nota(self) -> None:
        self.assertIn(
            "exige `nota`", self._erros(documento(segredos=[entrada(consumidores=[])]))
        )

    def test_instancias_fora_do_dominio(self) -> None:
        self.assertIn(
            "fora de", self._erros(documento(segredos=[entrada(instancias="por_tenant")]))
        )

    def test_anel_e_kid_tem_de_ser_booleanos(self) -> None:
        for campo in ("anel", "kid"):
            with self.subTest(campo=campo):
                self.assertIn(
                    f"`{campo}` tem de ser true ou false",
                    self._erros(documento(segredos=[entrada(**{campo: "sim"})])),
                )

    def test_fonte_sem_linha_exige_introduzido_por(self) -> None:
        self.assertIn(
            "exige `introduzido_por`",
            self._erros(documento(segredos=[entrada(fonte_08_5="-")])),
        )

    def test_excepcao_de_analise_sem_razao(self) -> None:
        # Uma excepcao sem razao escrita e uma excepcao que ninguem revoga.
        self.assertIn(
            "falta `razao`",
            self._erros(documento(analise_excluir=[{"caminho": "x", "razao": ""}])),
        )

    def test_excepcao_de_analise_sem_caminho(self) -> None:
        self.assertIn(
            "falta `caminho`",
            self._erros(documento(analise_excluir=[{"razao": "porque"}])),
        )


class TestCanon(unittest.TestCase):
    def test_le_as_linhas_do_doc_08(self) -> None:
        linhas = segredos_do_doc_08(RAIZ)
        self.assertIn("Meta App Secret", linhas)
        self.assertIn("Credenciais de BD", linhas)
        self.assertIn("Acesso humano", linhas)
        # Se o doc 08 §5 crescer, este numero muda — e a cobertura falha ate
        # alguem acrescentar a entrada. E esse o objectivo.
        self.assertEqual(len(linhas), 11)

    def test_le_os_codigos_do_catalogo(self) -> None:
        codigos = componentes_do_doc_00(RAIZ)
        for codigo in ("GWY", "CHR", "AGR", "PAY", "LLM", "HND", "ENT"):
            self.assertIn(codigo, codigos)
        self.assertNotIn("Fase", codigos)

    def test_normalizar_tira_acentos_backticks_e_negrito(self) -> None:
        self.assertEqual(normalizar("`verify_token` do webhook"), "verify_token do webhook")
        self.assertEqual(normalizar("PIN 2FA do número"), "pin 2fa do numero")
        self.assertEqual(normalizar("**Doppler**  x"), "doppler x")


class TestInventarioReal(unittest.TestCase):
    """O inventario que esta no repositorio tem de passar, hoje."""

    def setUp(self) -> None:
        self.inventario, self.erros = carregar(RAIZ)

    def test_esquema_valido(self) -> None:
        self.assertEqual(self.erros, [])

    def test_cobertura_de_cem_por_cento(self) -> None:
        cobertas, em_falta = cobertura(RAIZ, self.inventario)
        self.assertEqual(em_falta, [], "linhas do doc 08 §5 sem entrada")
        self.assertEqual(len(cobertas), 11)

    def test_sem_entradas_orfas(self) -> None:
        self.assertEqual([s.id for s in orfas(RAIZ, self.inventario)], [])

    def test_uma_gralha_na_fonte_e_apanhada(self) -> None:
        # Sem esta verificacao, uma gralha no rotulo faria a cobertura descer sem
        # ninguem saber onde.
        inventario, erros = validar(
            documento(segredos=[entrada(fonte_08_5="Meta App Secreto")]), COMPONENTES
        )
        self.assertEqual(erros, [])
        self.assertEqual([s.id for s in orfas(RAIZ, inventario)], ["meta_app_secret"])

    def test_todo_o_segredo_com_anel_tem_sentido(self) -> None:
        # O criterio de aceitacao nomeia o Meta App Secret; o anel e mais largo,
        # mas tem de existir onde o KAM-013 e o KAM-072 contam com ele.
        self.assertTrue(self.inventario.por_id["meta_app_secret"].anel)
        self.assertTrue(self.inventario.por_id["pepper_contact_hmac"].kid)

    def test_nenhuma_entrada_parece_conter_um_valor(self) -> None:
        # Um inventario diz que segredos existem; nao os guarda. Esta e a
        # verificacao mais barata de que ninguem colou um valor numa `nota`.
        suspeitos = ("sk-", "ghp_", "AKIA", "-----BEGIN", "xoxb-", "Bearer ")
        for segredo in self.inventario.segredos:
            texto = " ".join(filter(None, (segredo.nota, segredo.id)))
            for suspeito in suspeitos:
                self.assertNotIn(suspeito, texto, f"{segredo.id}: parece um valor")


if __name__ == "__main__":
    unittest.main()
