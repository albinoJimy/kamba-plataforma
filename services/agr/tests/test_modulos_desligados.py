"""KAM-127, criterio 5 e 8: desligar um modulo de entrada pelo registo.

O `registry/modulos_entrada.yaml` com `activo: false` e o efeito de um abate.
Prova-se aqui, sem base:

* o leitor (`registo.modulos_desligados`) — o ficheiro real, um modulo
  desligado, e o que falha o arranque em vez de ler «ligado»;
* que o `load_all` salta a quinta forma, como salta os planos e o consumidor;
* a ToolLayer real: com **cada um** dos quatro modulos desligado, so as tools
  dele recusam, com `ENTITLEMENT_DENIED`, antes de ler o entitlement; as dos
  outros modulos e a `get_store_info` do atendimento continuam (o teste de
  regressao do criterio 5);
* o grafo do dono de ponta a ponta: o dono recebe a frase **estatica** que o
  modulo ja tinha para «nao activo».
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from kamba_agr import registo
from kamba_agr.catalogo.montagem import MODULO_DA_FOTO, EnhancePorEntitlement
from kamba_agr.tls import erros
from kamba_agr.tls.camada import ToolLayer
from kamba_agr.tls.catalogo import catalogo_do_piloto
from kamba_agr.tls.especificacoes import Catalogo
from kamba_agr.verticais.dono import social as conversa_social
from test_dono import _ligada, _LigacaoDosModulos
from test_grafos import RAIZ
from test_registo import GATES, VENDEDOR, ambiente, escrever
from test_social_dono import Mundo
from test_tls import contexto

#: Uma tool real de cada modulo de entrada com tools, com o `modulo` que o
#: catalogo real lhe da, e a `get_store_info`, que nao tem modulo proprio
#: (fecha-se pelo do canal) e e do atendimento. **O `foto` nao tem tool na
#: ToolLayer**: chega-se a ele pela oferta «melhorar foto» do catalogo, e e la
#: que o interruptor morde (`TestAFoto`).
TOOL_DE_CADA_MODULO = {
    "catalogo": "get_catalog_status",
    "social": "get_brand_profile",
    "orcamento": "submit_quote",
}
DO_ATENDIMENTO = "get_store_info"
TODOS = {"vendedor", "catalogo", "foto", "social", "orcamento"}


def _modulo_real(nome: str) -> str | None:
    return catalogo_do_piloto()[nome].modulo


class TestOLeitor(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_o_registo_do_repositorio_nao_desliga_nada(self) -> None:
        self.assertEqual(registo.modulos_desligados(RAIZ / "registry"), frozenset())

    def test_um_modulo_com_activo_false_e_desligado(self) -> None:
        escrever(
            self.pasta,
            qualquer_nome=(
                "version: 1.0.0\nmodulos_entrada:\n"
                "  - {modulo: catalogo, activo: true, abatavel: false}\n"
                "  - {modulo: foto, activo: false, abatavel: true}\n"
            ),
        )
        self.assertEqual(registo.modulos_desligados(self.pasta), frozenset({"foto"}))

    def test_sem_ficheiro_nenhum_nada_esta_desligado(self) -> None:
        escrever(self.pasta, vendedor=VENDEDOR)
        self.assertEqual(registo.modulos_desligados(self.pasta), frozenset())

    def test_um_interruptor_ilegivel_falha_o_arranque(self) -> None:
        for mau in ('"false"', "0", "null"):
            with self.subTest(activo=mau):
                escrever(self.pasta, m=f"modulos_entrada:\n  - {{modulo: foto, activo: {mau}}}\n")
                with self.assertRaises(registo.RegistoInvalidoError):
                    registo.modulos_desligados(self.pasta)

    def test_o_mesmo_modulo_duas_vezes_e_dois_ficheiros_falham(self) -> None:
        escrever(
            self.pasta,
            m="modulos_entrada:\n  - {modulo: foto, activo: true}\n  - {modulo: foto, activo: false}\n",
        )
        with self.assertRaisesRegex(registo.RegistoInvalidoError, "duas vezes"):
            registo.modulos_desligados(self.pasta)
        escrever(
            self.pasta,
            m="modulos_entrada:\n  - {modulo: foto, activo: true}\n",
            n="modulos_entrada:\n  - {modulo: social, activo: true}\n",
        )
        with self.assertRaisesRegex(registo.RegistoInvalidoError, "num so"):
            registo.modulos_desligados(self.pasta)

    def test_o_load_all_salta_a_quinta_forma(self) -> None:
        escrever(
            self.pasta,
            vendedor=VENDEDOR,
            gates=GATES,
            modulos="version: 1.0.0\nmodulos_entrada:\n  - {modulo: foto, activo: false, abatavel: true}\n",
        )
        verticais, _, _ = registo.carregar(ambiente(), self.pasta)
        self.assertEqual(set(verticais), {"vendedor"})


class TestATooLayer(unittest.TestCase):
    """O criterio 5: desligar um modulo nao afecta os outros nem o atendimento."""

    def _camada(self, desligados: frozenset[str]) -> tuple[ToolLayer, _LigacaoDosModulos]:
        nomes = (*TOOL_DE_CADA_MODULO.values(), DO_ATENDIMENTO)
        especificacoes = tuple(_ligada(nome, _modulo_real(nome)) for nome in nomes)
        ligacao = _LigacaoDosModulos(set(TODOS))
        camada = ToolLayer(Catalogo(especificacoes), abrir_ligacao=ligacao.nova_vaga, modulos_desligados=desligados)
        return camada, ligacao

    def _invocar(self, camada: ToolLayer, nome: str):
        return asyncio.run(
            camada.invoke(
                contexto(vertical="vendedor", turn_id=f"m-{nome}"),
                nome,
                {"cart_id": "c-1"},
                allowed=(*TOOL_DE_CADA_MODULO.values(), DO_ATENDIMENTO),
                confirmation=None,
                idempotency_key=None,
            )
        )

    def test_as_tools_do_ensaio_sao_de_cada_modulo_no_catalogo_real(self) -> None:
        for modulo, nome in TOOL_DE_CADA_MODULO.items():
            with self.subTest(modulo=modulo):
                self.assertEqual(_modulo_real(nome), modulo)
        self.assertIsNone(_modulo_real(DO_ATENDIMENTO))

    def test_tudo_ligado_tudo_responde(self) -> None:
        camada, _ = self._camada(frozenset())
        for nome in (*TOOL_DE_CADA_MODULO.values(), DO_ATENDIMENTO):
            with self.subTest(tool=nome):
                self.assertTrue(self._invocar(camada, nome).ok)

    def test_cada_modulo_desligado_so_recusa_as_suas(self) -> None:
        for desligado, da_desligada in TOOL_DE_CADA_MODULO.items():
            with self.subTest(desligado=desligado):
                camada, ligacao = self._camada(frozenset({desligado}))
                recusa = self._invocar(camada, da_desligada)
                self.assertFalse(recusa.ok)
                self.assertEqual(recusa.error.codigo, erros.ENTITLEMENT_DENIED)
                self.assertIn("desligado no registo", recusa.error.detalhe)
                for outro, nome in TOOL_DE_CADA_MODULO.items():
                    if outro != desligado:
                        self.assertTrue(self._invocar(camada, nome).ok, f"{nome} com {desligado} desligado")
                self.assertTrue(self._invocar(camada, DO_ATENDIMENTO).ok)
                # Recusado antes do entitlement: o modulo desligado nunca se pediu a base.
                self.assertNotIn(desligado, ligacao.modulos_pedidos())

    def test_um_nome_que_nao_e_modulo_de_tool_nao_desliga_o_atendimento(self) -> None:
        """O interruptor so le o `modulo` da tool, e nunca o da vertical do canal."""
        camada, _ = self._camada(frozenset({"vendedor"}))
        self.assertTrue(self._invocar(camada, DO_ATENDIMENTO).ok)


class TestAFoto(unittest.TestCase):
    """O quarto modulo: a oferta de «melhorar foto» desligada pelo registo."""

    def test_desligado_nao_oferece_nem_le_o_entitlement(self) -> None:
        lidos: list[tuple[str, str]] = []

        def ler(tenant: str, modulo: str):
            lidos.append((tenant, modulo))
            return type("E", (), {"ativo": True})()

        self.assertFalse(EnhancePorEntitlement(ler, desligado=True).disponivel("t-1"))
        self.assertEqual(lidos, [])
        self.assertTrue(EnhancePorEntitlement(ler).disponivel("t-1"))
        self.assertEqual(lidos, [("t-1", MODULO_DA_FOTO)])

    def test_nenhuma_tool_da_toollayer_e_do_foto(self) -> None:
        """Se uma vier a ser, o passo 2 desliga-a sem mudar nada: este ensaio diz onde olhar."""
        catalogo = catalogo_do_piloto()
        self.assertNotIn(MODULO_DA_FOTO, {catalogo[n].modulo for n in catalogo.nomes()})


class TestOOrcamentoForaDaToolLayer(unittest.TestCase):
    """O `orcamento` tem tres portas fora da ToolLayer, e as tres obedecem ao interruptor.

    Sem isto o cliente via o botao «Pedir orcamento» (que le so o entitlement) e
    recebia a recusa do `request_quote` ao carregar nele, e uma proposta
    respondida antes do abate saia na mesma.
    """

    def porta(self, desligado: bool):
        from kamba_agr.orcamento.porta import PortaDeOrcamento

        aberturas: list[int] = []

        def abrir():
            aberturas.append(1)
            raise AssertionError("desligado, a porta nao vai a base")

        return PortaDeOrcamento(abrir, desligado=desligado), aberturas

    def test_desligado_nao_oferece_nao_envia_e_nao_liberta_sem_ir_a_base(self) -> None:
        from kamba_agr.contexto import PERSONA_CLIENTE
        from kamba_agr.tls import orcamento as repositorio

        porta, aberturas = self.porta(desligado=True)
        self.assertFalse(asyncio.run(porta.activo("t-1")))
        envio = asyncio.run(porta.enviar("t-1", "c-1", "a-1"))
        self.assertEqual(envio.desfecho, repositorio.NAO_ENVIADO)
        invocacao = type("I", (), {"persona": PERSONA_CLIENTE, "tenant_id": "t-1", "contact_id": "c-1"})()
        self.assertEqual(asyncio.run(porta.libertar(invocacao)), [])
        self.assertEqual(aberturas, [])

    def test_ligado_pergunta_a_base(self) -> None:
        porta, aberturas = self.porta(desligado=False)
        with self.assertRaises(AssertionError):
            asyncio.run(porta.activo("t-1"))
        self.assertEqual(aberturas, [1])


class TestOGrafoDoDono(unittest.TestCase):
    def test_o_dono_recebe_a_frase_estatica_do_modulo(self) -> None:
        mundo = Mundo()
        mundo.camada = ToolLayer(
            mundo.camada.catalogo,
            abrir_ligacao=mundo.ligacao.nova_vaga,
            modulos_desligados=frozenset({"social"}),
        )
        _final, texto, _ = mundo.turno("IDEIAS")
        self.assertTrue(texto.endswith(conversa_social.MSG_SOCIAL_INACTIVO), texto)


if __name__ == "__main__":
    unittest.main()
