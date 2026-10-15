"""Suite de contrato de `StorageProvider`, nos alvos que correm sem contentor
(KAM-011).

A bateria esta em `storage_contrato.py` e e a mesma que
`tests/integracao/test_storage_s3real.py` corre contra um servidor S3 real. Aqui
corre duas vezes:

- sobre o ***fake***, que e o que os consumidores usam nos seus testes;
- sobre o **motor S3 ligado a um servidor S3 em memoria** — o mesmo codigo de
  producao (assinatura, XML, envio em partes), com a rede trocada por uma
  funcao.

O segundo alvo **nao** e a prova de que o motor fala S3: o servidor em memoria
foi escrito por quem escreveu o motor. Essa prova e a de
`docs/evidencia/KAM-011-seaweedfs.md`.
"""

from __future__ import annotations

import unittest

from storage_apoio import Alvo, alvo_fake, alvo_s3_em_memoria
from storage_contrato import BateriaDeContrato

from kamba_core.storage import StorageProvider


class ContratoNoFake(BateriaDeContrato, unittest.TestCase):
    def criar_alvo(self) -> Alvo:
        return alvo_fake()


class ContratoNoS3EmMemoria(BateriaDeContrato, unittest.TestCase):
    def criar_alvo(self) -> Alvo:
        return alvo_s3_em_memoria()


class TrocarDeImplementacaoESoConfiguracao(unittest.TestCase):
    def test_os_dois_alvos_sao_a_mesma_porta(self) -> None:
        for alvo, nome in ((alvo_fake(), "fake"), (alvo_s3_em_memoria(), "s3")):
            self.assertIsInstance(alvo.storage, StorageProvider)
            self.assertEqual(alvo.storage.nome, nome)


if __name__ == "__main__":
    unittest.main()
