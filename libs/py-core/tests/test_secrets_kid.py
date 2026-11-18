"""O `kid` lido do valor, do lado Python (KAM-205).

Espelho do `packages/core-ts/tests/kid.test.ts` na parte do provedor: as duas
portas tem de significar o mesmo (`kamba_core/secrets/port.py`). Nenhuma chave e
literal: saem todas do `os.urandom` em execucao.
"""

from __future__ import annotations

import base64
import json
import os
import unittest

from kamba_core.secrets import (
    DopplerSecretProvider,
    EnvSecretProvider,
    KidRepetidoNoCofreError,
    RespostaHttp,
    SecretAusenteError,
    kid_do_valor,
    kids_das_versoes,
    separar_kid,
)

VAR = "KAMBA_SECRET_KEK_TOKEN_CLIENTE"
REF = "kek_token_cliente"


def chave(octetos: int = 32) -> str:
    return base64.b64encode(os.urandom(octetos)).decode("ascii")


class TestKidNoValor(unittest.TestCase):
    def test_separa_e_recusa_o_que_nao_e_uma_chave_nossa(self) -> None:
        c = chave()
        self.assertEqual(separar_kid(f"20261118.abcdefgh:{c}"), ("20261118.abcdefgh", c))
        for valor in (
            c,
            "utilizador:segredo-que-nao-e-base64",
            f"K1:{c}",
            f":{c}",
            f"k1:{chave(31)}",
            f"k1:{chave(33)}",
            f"actual:{c}",
            f"anterior:{c}",
        ):
            self.assertIsNone(kid_do_valor(valor), f"{len(valor)} caracteres")

    def test_o_kid_do_valor_e_so_sem_ele_o_rotulo_da_posicao(self) -> None:
        a, b = f"k2:{chave()}", f"k1:{chave()}"
        self.assertEqual(kids_das_versoes(REF, a, b), ("k2", "k1"))
        self.assertEqual(kids_das_versoes(REF, a, chave()), ("k2", "anterior"))
        self.assertEqual(kids_das_versoes("meta_app_secret", chave(), chave()), ("actual", "anterior"))
        self.assertEqual(kids_das_versoes("db_pay_password", "kamba_app:senha-de-ensaio", None), ("actual",))

    def test_o_mesmo_kid_nas_duas_e_recusado_sem_o_valor(self) -> None:
        a, b = f"k1:{chave()}", f"k1:{chave()}"
        with self.assertRaises(KidRepetidoNoCofreError) as caso:
            kids_das_versoes(REF, a, b)
        self.assertNotIn(a[3:], str(caso.exception))
        self.assertNotIn(b[3:], str(caso.exception))


class TestProvedores(unittest.TestCase):
    def test_env_a_mesma_versao_tem_o_mesmo_kid_antes_e_depois_de_passar_a_anterior(self) -> None:
        k1 = f"k1:{chave()}"
        self.assertEqual(EnvSecretProvider("staging", {VAR: k1}).versions(REF), ("k1",))
        rodado = EnvSecretProvider("staging", {VAR: f"k2:{chave()}", f"{VAR}_ANTERIOR": k1})
        self.assertEqual(rodado.versions(REF), ("k2", "k1"))
        with self.assertRaises(KidRepetidoNoCofreError):
            EnvSecretProvider("staging", {VAR: k1, f"{VAR}_ANTERIOR": k1}).versions(REF)
        with self.assertRaises(SecretAusenteError):
            EnvSecretProvider("dev", {}).versions(REF)

    def test_doppler_le_o_kid_da_mesma_maneira(self) -> None:
        corpo = json.dumps({VAR: f"k2:{chave()}", f"{VAR}_ANTERIOR": f"k1:{chave()}"})
        doppler = DopplerSecretProvider(
            ambiente="prod",
            projecto="kamba",
            config="prod",
            token_servico="ensaio",
            transporte=lambda _url, _cabecalhos: RespostaHttp(200, corpo),
            ttl_descarga_s=0,
        )
        self.assertEqual(doppler.versions(REF), ("k2", "k1"))


if __name__ == "__main__":
    unittest.main()
