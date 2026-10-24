"""As duas ligacoes do AGR, e a paridade com o `db/ligacao.py`.

O `kamba_agr/ligacao.py` **le** as variaveis que o `db/ligacao.py` (KAM-003)
definiu; nao as define outra vez. O que impede as duas de divergirem e esta
bateria, e nao uma intencao — e a mesma resposta que o `ten/consultas.py` deu ao
mesmo problema entre Python e TypeScript.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from apoio import invocacao_crua
from kamba_agr.contexto import ler_invocacao
from kamba_agr.ligacao import (
    NOME_DA_LEITURA,
    NOME_DA_TRANCA,
    PAPEL,
    VAR_BASE,
    VAR_HOST,
    VAR_PORTA,
    VAR_SENHA,
    ConfiguracaoEmFalta,
    _ligar,
)

RAIZ = Path(__file__).resolve().parents[3]


def _db_ligacao():
    """Carrega `db/ligacao.py` pelo caminho: nao e um pacote importavel."""
    caminho = RAIZ / "db" / "ligacao.py"
    nome = "db_ligacao_para_paridade"
    spec = importlib.util.spec_from_file_location(nome, caminho)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    # Registar **antes** do `exec_module`: o `db/ligacao.py` tem um
    # `@dataclasses.dataclass`, e o `dataclasses` resolve as anotacoes indo a
    # `sys.modules[cls.__module__].__dict__`. Sem o registo, isso e `None` e o
    # `exec_module` morre com `AttributeError: 'NoneType' object has no
    # attribute '__dict__'`. Medido.
    sys.modules[nome] = modulo
    try:
        spec.loader.exec_module(modulo)
    except BaseException:
        del sys.modules[nome]
        raise
    return modulo


class TestParidadeComODbLigacao(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _db_ligacao()

    def test_o_papel_e_o_mesmo(self) -> None:
        self.assertEqual(PAPEL, self.db.PAPEIS["app"])

    def test_as_tres_variaveis_de_destino_sao_as_mesmas(self) -> None:
        # O `db/ligacao.py` nao as exporta como constantes; le-as com os nomes
        # literais. Confronta-se contra o **texto**, que e o que pode divergir.
        fonte = (RAIZ / "db" / "ligacao.py").read_text(encoding="utf-8")
        for variavel in (VAR_HOST, VAR_PORTA, VAR_BASE):
            with self.subTest(variavel=variavel):
                self.assertIn(f'"{variavel}"', fonte)

    def test_a_variavel_da_senha_e_a_mesma(self) -> None:
        self.assertEqual(VAR_SENHA, self.db.VARIAVEL_DA_SENHA["app"])

    def test_nao_ha_variavel_nova_para_o_agr(self) -> None:
        # Um segundo conjunto de nomes para a mesma base e o defeito que o
        # §3.13 ja pagou a inventar `KAMBA_CHR_*_DB_URL`.
        import kamba_agr.ligacao as modulo

        variaveis = {
            getattr(modulo, nome) for nome in dir(modulo) if nome.startswith("VAR_")
        }
        conhecidas = {"KAMBA_DB_HOST", "KAMBA_DB_PORT", "KAMBA_DB_NAME"} | set(
            self.db.VARIAVEL_DA_SENHA.values()
        )
        self.assertTrue(variaveis <= conhecidas, variaveis - conhecidas)


class TestConfiguracao(unittest.TestCase):
    def test_sem_a_senha_levanta_e_nomeia_a_variavel(self) -> None:
        with self.assertRaises(ConfiguracaoEmFalta) as apanhado:
            _ligar({"KAMBA_DB_NAME": "kamba_platform"}, False, "x")
        self.assertIn(VAR_SENHA, str(apanhado.exception))

    def test_sem_o_nome_da_base_levanta(self) -> None:
        with self.assertRaises(ConfiguracaoEmFalta) as apanhado:
            _ligar({VAR_SENHA: "nao e um segredo a serio"}, False, "x")
        self.assertIn(VAR_BASE, str(apanhado.exception))

    def test_uma_porta_que_nao_e_numero_levanta(self) -> None:
        with self.assertRaises(ConfiguracaoEmFalta) as apanhado:
            _ligar(
                {
                    VAR_SENHA: "nao e um segredo a serio",
                    VAR_BASE: "kamba_platform",
                    VAR_PORTA: "cinco mil",
                },
                False,
                "x",
            )
        self.assertIn(VAR_PORTA, str(apanhado.exception))

    def test_a_mensagem_nunca_leva_o_valor(self) -> None:
        # «Uma variavel em falta levanta um erro que nomeia a variavel e nunca o
        # valor» — `db/ligacao.py`, e a mesma regra deste lado. O valor de teste
        # tem forma de telemovel angolano de proposito.
        with self.assertRaises(ConfiguracaoEmFalta) as apanhado:
            _ligar(
                {
                    VAR_SENHA: "923456789 nao e um segredo",
                    VAR_PORTA: "923456789x",
                    VAR_BASE: "kamba_platform",
                },
                False,
                "x",
            )
        self.assertIn(VAR_PORTA, str(apanhado.exception))
        self.assertNotIn("923456789", str(apanhado.exception))


class TestOsDoisUsos(unittest.TestCase):
    def test_os_application_name_distinguem_as_duas(self) -> None:
        # E o que torna diagnosticavel uma tranca presa em `pg_stat_activity`.
        self.assertNotEqual(NOME_DA_LEITURA, NOME_DA_TRANCA)
        self.assertTrue(NOME_DA_LEITURA.startswith("kamba-agr:"))
        self.assertTrue(NOME_DA_TRANCA.startswith("kamba-agr:"))

    def test_a_da_tranca_e_autocommit_e_a_de_leitura_nao(self) -> None:
        """As duas portas pedem o que dizem pedir, sem abrir ligacao nenhuma.

        Que o `autocommit` tenha o efeito que se descreve — a tranca de sessao a
        sobreviver ao fim da instrucao — mede-se contra a base, na *suite*
        `db/tests_agr/` do *gate* 8. Aqui so se confere o pedido.
        """
        import kamba_agr.ligacao as modulo

        pedidos: list[tuple[bool, str]] = []

        class LigacaoFalsa:
            autocommit = None

        def espia(_ambiente, autocommit, nome):
            pedidos.append((autocommit, nome))
            ligacao = LigacaoFalsa()
            ligacao.autocommit = autocommit
            return ligacao

        original = modulo._ligar
        modulo._ligar = espia  # type: ignore[assignment]
        self.addCleanup(setattr, modulo, "_ligar", original)

        self.assertTrue(modulo.ligar_para_tranca({}).autocommit)
        self.assertFalse(modulo.ligar_para_leitura({}).autocommit)
        self.assertEqual(
            pedidos, [(True, NOME_DA_TRANCA), (False, NOME_DA_LEITURA)]
        )


class TestLigacaoQuebrada(unittest.IsolatedAsyncioTestCase):
    """Uma ligacao morta larga-se; a tentativa seguinte abre outra.

    Sem isto, um corte de rede ou um reinicio do PostgreSQL deixava a ligacao
    quebrada guardada no objecto, e **todos** os turnos deste processo falhavam
    ate alguem reiniciar o servico. Nao da erro de arranque, nao aparece numa
    sonda, e um teste de unidade sobre o caminho feliz nao o ve. Encontrado na
    revisao adversarial do proprio ticket.
    """

    class LigacaoQuePara:
        """Responde `vezes_boas` vezes e depois rebenta. Conta os `close`."""

        def __init__(self, vezes_boas: int = 0) -> None:
            self.vezes_boas = vezes_boas
            self.fechada = 0

        def cursor(self):
            ligacao = self

            class Cursor:
                def execute(self, _sql, _args=None):
                    if ligacao.vezes_boas <= 0:
                        raise OSError("a ligacao caiu")
                    ligacao.vezes_boas -= 1

                def fetchone(self):
                    return (True,)

                def close(self):
                    return None

            return Cursor()

        def close(self):
            self.fechada += 1

    async def test_a_tranca_larga_a_ligacao_morta_e_reabre(self) -> None:
        from kamba_agr.trancas import TrancaDeConversas

        abertas: list = []

        def abrir():
            nova = self.LigacaoQuePara(vezes_boas=0 if not abertas else 10)
            abertas.append(nova)
            return nova

        trancas = TrancaDeConversas(abrir)
        with self.assertRaises(OSError):
            async with trancas.tomar("a:b"):
                pass
        self.assertEqual(len(abertas), 1)
        self.assertEqual(abertas[0].fechada, 1, "a ligacao morta nao foi fechada")

        # A tentativa seguinte abre **outra** e funciona.
        async with trancas.tomar("a:b"):
            pass
        self.assertEqual(len(abertas), 2)

    async def test_o_leitor_larga_a_ligacao_morta_e_reabre(self) -> None:
        from kamba_agr.conversa import leitor

        abertas: list = []

        def abrir():
            nova = self.LigacaoQuePara(vezes_boas=0 if not abertas else 10)
            abertas.append(nova)
            return nova

        ler = leitor(abrir)
        invocacao = ler_invocacao(invocacao_crua())
        with self.assertRaises(Exception):
            await ler(invocacao)
        self.assertEqual(len(abertas), 1)
        self.assertEqual(abertas[0].fechada, 1)

        # A segunda ligacao responde, e a leitura chega ao `tenant_guard` —
        # que recusa uma ligacao sem `autocommit` definido como transaccional.
        # O que importa aqui e que **abriu outra**, e nao o desfecho da leitura.
        try:
            await ler(invocacao)
        except Exception:
            pass
        self.assertEqual(len(abertas), 2)

if __name__ == "__main__":
    unittest.main()
