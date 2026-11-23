"""As fotos do dono nao coalescem (KAM-231, achado 1 da revisao adversarial).

O estado de um turno sai da primeira invocacao do lote, e o `asset_id` e dela:
dez fotos de um album, a menos de 1,5 s umas das outras, davam **um** rascunho e
perdiam nove sem erro. Mede-se no `ExecutorDeTurnos` real, e nao chamando o
grafo dez vezes a seguir, que era o que o ensaio do rascunho fazia.
"""

from __future__ import annotations

import asyncio
import unittest
import uuid
from typing import Any

from apoio import invocacao_crua
from test_turno import GrafoEspia, executor

from kamba_agr.admissao import Tectos
from kamba_agr.contexto import ler_invocacao


def _foto(tenant: str, contacto: str) -> Any:
    return ler_invocacao(
        invocacao_crua(tenant_id=tenant, contact_id=contacto, persona="dono", type="image", asset_id=str(uuid.uuid4()))
    )


def _texto(tenant: str, contacto: str) -> Any:
    return ler_invocacao(invocacao_crua(tenant_id=tenant, contact_id=contacto, persona="dono"))


class _Espia(GrafoEspia):
    def __init__(self, vistos: list[Any], **k: Any) -> None:
        super().__init__(**k)
        self.vistos = vistos

    async def ainvoke(self, estado: Any, config: Any) -> Any:
        self.vistos.append(estado.get("asset_id"))
        return await super().ainvoke(estado, config)


class TestAsFotosNaoCoalescem(unittest.IsolatedAsyncioTestCase):
    async def _correr(self, invocacoes: list[Any]) -> list[Any]:
        vistos: list[Any] = []
        exec_, _, _ = executor(grafo=_Espia(vistos, atraso=0.05), tectos=Tectos(coalescencia_ms=1_500))
        desfechos = await asyncio.gather(*(exec_.correr(i) for i in invocacoes))
        self.desfechos = desfechos
        return vistos

    async def test_dez_fotos_de_um_album_sao_dez_turnos(self) -> None:
        t, c = str(uuid.uuid4()), str(uuid.uuid4())
        fotos = [_foto(t, c) for _ in range(10)]
        vistos = await self._correr(fotos)
        self.assertEqual(sorted(vistos), sorted(f.asset_id for f in fotos))
        self.assertTrue(all(d.coalescidos == 0 for d in self.desfechos), [d.coalescidos for d in self.desfechos])

    async def test_uma_foto_e_um_texto_sao_dois_turnos_nas_duas_ordens(self) -> None:
        for ordem in ("foto_primeiro", "texto_primeiro"):
            with self.subTest(ordem=ordem):
                t, c = str(uuid.uuid4()), str(uuid.uuid4())
                foto, texto = _foto(t, c), _texto(t, c)
                vistos = await self._correr([foto, texto] if ordem == "foto_primeiro" else [texto, foto])
                self.assertEqual(len(vistos), 2)
                self.assertIn(foto.asset_id, vistos)

    async def test_os_textos_continuam_a_coalescer(self) -> None:
        t, c = str(uuid.uuid4()), str(uuid.uuid4())
        vistos = await self._correr([_texto(t, c) for _ in range(3)])
        self.assertEqual(len(vistos), 1)


if __name__ == "__main__":
    unittest.main()
