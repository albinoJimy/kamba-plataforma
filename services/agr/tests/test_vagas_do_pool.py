"""As vagas do *pool* da `ToolLayer` nos ensaios: uma identidade cada, o mesmo estado.

KAM-181. O *pool* da camada tem `KAMBA_TLS_LIGACOES` vagas
(`LIGACOES_POR_OMISSAO = 4`) e **cada vaga vazia chama a fabrica**
(`tls/camada.py`, `_correr`: `vaga if vaga is not None else self._abrir_ligacao()`).
Quatro fixturas dos ensaios do AGR passavam uma fabrica que devolvia sempre **o
mesmo objecto**, pelo que as quatro vagas ficavam com a mesma ligacao; duas
invocacoes concorrentes na mesma ligacao fazem o `tenant_guard` levantar
`LigacaoEmUso` — **com razao**, porque uma segunda transaccao sobrepunha o
contexto de tenant da primeira. O defeito era da fabrica do ensaio, nao do
guarda.

**O custo foi atribuir-se o vermelho ao ramo errado, e a prova fica aqui** —
porque e ela que tem de sobreviver a fusao deste ticket. No PR `#137` (KAM-180,
medido a 2026-11-05) o `gate 4` falhou em `ordem-dos-ensaios` com
`kamba_core.tenant_guard.LigacaoEmUso`, e esse PR **nao toca no caminho**:
`git diff --name-only publico/main...HEAD -- services/ libs/` dava **0
ficheiros**, e um `gh run rerun --failed` sobre o **mesmo commit** passou. O
vermelho nao era dele nem da `main` — era desta fabrica.

**Porque e que este ficheiro nao conta repeticoes.** As taxas de vermelho sem
carga sao 0 % a `pool=1`, ~0,8 % a `pool=2`, ~1,5 % a `pool=4` e ~3,8 % a
`pool=16` (tabela do §Contexto de `specs/tickets/KAM-181.md`), pelo que uma
matriz de 4 x 30
repeticoes fecha **verde numa arvore nao corrigida** entre um terco e metade das
vezes: seria satisfeita sem correccao nenhuma. O que se mede aqui e a
**identidade** das vagas e a **partilha** do estado — as duas metades, e as duas
deterministicas, numa corrida. As repeticoes do caso das cinquenta confirmacoes
ficam para o relatorio do ticket, com a carga declarada.

**E mede-se nas fixturas e nao numa camada montada aqui.** Uma copia local da
forma correcta ficava verde com os quatro sitios por corrigir: o que se afirma e
a **ligacao** da fabrica ao sitio que a usa, e nao a fabrica sozinha. Por isso
estes ensaios vao buscar as quatro fixturas, e tocam no `_abrir_ligacao` e no
`_tomadas` da camada — privados, e lidos de proposito, como o
`test_a_fila_e_o_tecto_de_tomadas` do `test_tls.py` ja faz: o *pool* e o sujeito.
"""

from __future__ import annotations

import os
import unittest
from typing import Any, Callable
from unittest import mock

import test_regra_de_dois
import test_servicos
import test_tls
import test_vendedor
from kamba_agr.tls.camada import LIGACOES_POR_OMISSAO, VARIAVEL_DE_LIGACOES
from kamba_core import tenant_guard
from test_tls import TENANT, _Ligacao

#: Os tamanhos de *pool* do criterio 2 do KAM-181. O **1 e o controlo**: com uma
#: vaga nao ha partilha possivel, e foi a `pool=1` que o defeito deu 0 vermelhas
#: em 160 corridas — e o que mostrou que a causa nao era do guarda nem da camada.
POOLS = (1, 2, 4, 16)

#: Os campos de `_Ligacao` que as baterias lêem **depois** de a camada correr: a
#: `platform.tool_idempotency` em memoria, o SQL gravado e as respostas
#: enlatadas. Sao estes que tem de continuar a ser **os mesmos objectos** em
#: todas as vagas; e a `idempotencia` e a que o `ON CONFLICT DO NOTHING` do
#: `_idem_reservar` usa para serializar, logo e a que a correccao ingenua parte.
ESTADO_PARTILHADO = ("idempotencia", "sql", "respostas")


def _fixturas() -> dict[str, tuple[Callable[[], Any], Any]]:
    """Os quatro sitios, cada um com a sua fabrica e a ligacao que a fixtura devolve.

    A fabrica e a que a fixtura passou ao `abrir_ligacao`; a ligacao e a que ela
    poe na mao do ensaio, e que e a **janela** para o estado das vagas.
    """
    _, deps_do_vendedor, _, _, lig_do_vendedor = test_vendedor.montar()
    _, deps_de_servicos, _, _, lig_de_servicos = test_servicos.montar()
    runtime = test_regra_de_dois.Runtime()
    # `_Base` e a fixtura do quarto sitio e nao tem metodos de teste. O
    # `unittest` deixa construir uma `TestCase` com `"runTest"` mesmo quando
    # esse metodo nao existe (so se queixa a correr, e aqui nao se corre nada):
    # o que se quer dela e a `camada()`.
    camada_do_tls, lig_do_tls, _ = test_tls._Base("runTest").camada()

    return {
        "test_vendedor.py (montar)": (
            deps_do_vendedor.tools._abrir_ligacao,
            lig_do_vendedor,
        ),
        "test_servicos.py (montar)": (
            deps_de_servicos.tools._abrir_ligacao,
            lig_de_servicos,
        ),
        "test_regra_de_dois.py (Runtime)": (
            runtime.tools._abrir_ligacao,
            runtime.ligacao,
        ),
        "test_tls.py (_Base.camada)": (
            camada_do_tls._abrir_ligacao,
            lig_do_tls,
        ),
    }


class TestIdentidadeDasVagas(unittest.TestCase):
    """Criterio 2 do KAM-181: a identidade das vagas, deterministica."""

    def test_cada_vaga_recebe_uma_identidade_distinta(self) -> None:
        """`len({id(l)})` igual ao numero de vagas, nos quatro tamanhos de pool.

        Esta e a caixa 2. Com a fabrica a devolver sempre o mesmo objecto, isto
        da 1 para qualquer *pool* maior do que 1 — e da-o **sempre**, que e a
        diferenca entre isto e contar repeticoes.
        """
        for sitio, (fabrica, _) in _fixturas().items():
            for quantas in POOLS:
                with self.subTest(sitio=sitio, pool=quantas):
                    vagas = [fabrica() for _ in range(quantas)]
                    identidades = {id(vaga) for vaga in vagas}
                    self.assertEqual(
                        len(identidades),
                        quantas,
                        f"{sitio}: {quantas} vagas com {len(identidades)} "
                        "identidades — duas vagas partilham a ligacao, e duas "
                        "invocacoes concorrentes levantam `LigacaoEmUso`",
                    )

    def test_a_ligacao_da_fixtura_nao_e_nenhuma_das_vagas(self) -> None:
        """A que o ensaio tem na mao e a janela, e nao uma das tomadas.

        Se fosse uma delas, a camada entregava-a a uma vaga e o ensaio ficava a
        partilhar ligacao com o *pool* — que e exactamente o defeito.
        """
        for sitio, (fabrica, ligacao) in _fixturas().items():
            with self.subTest(sitio=sitio):
                vagas = [fabrica() for _ in range(max(POOLS))]
                self.assertNotIn(id(ligacao), {id(vaga) for vaga in vagas})

    def test_as_vagas_partilham_o_estado_que_as_baterias_medem(self) -> None:
        """A outra metade do criterio 1 — e a que a correccao ingenua parte.

        `abrir_ligacao=_Ligacao` resolvia a identidade e dava a cada vaga a
        **sua** `platform.tool_idempotency`. Medido na arvore sem esta
        verificacao, as cinquenta confirmacoes concorrentes passavam a dar
        `AssertionError: N != 1` com `N` igual ao tamanho do *pool*, em 12 de 12
        corridas. Aqui o sintoma aparece sem concorrencia nenhuma.
        """
        for sitio, (fabrica, ligacao) in _fixturas().items():
            vagas = [fabrica() for _ in range(max(POOLS))]
            for campo in ESTADO_PARTILHADO:
                with self.subTest(sitio=sitio, campo=campo):
                    objectos = {id(getattr(vaga, campo)) for vaga in vagas}
                    objectos.add(id(getattr(ligacao, campo)))
                    self.assertEqual(
                        len(objectos),
                        1,
                        f"{sitio}: a `{campo}` nao e a mesma em todas as vagas "
                        "— cada vaga ficou com a sua, e deixa de haver o que "
                        "serialize as confirmacoes concorrentes",
                    )

    def test_o_que_uma_vaga_escreve_na_tabela_a_outra_le(self) -> None:
        """A partilha medida pelo efeito, e nao so pela identidade do `dict`."""
        for sitio, (fabrica, ligacao) in _fixturas().items():
            with self.subTest(sitio=sitio):
                primeira, segunda = fabrica(), fabrica()
                primeira.idempotencia["k-181"] = [
                    "em_curso",
                    b"\x00",
                    None,
                    ligacao.agora,
                ]
                self.assertIn("k-181", segunda.idempotencia)
                self.assertIn("k-181", ligacao.idempotencia)


class TestOPoolAServirVagas(unittest.TestCase):
    """A cadeia inteira: a fila da camada a entregar vagas, e nao so a fabrica.

    Uma fabrica correcta ligada ao sitio errado passa todos os ensaios dela. Por
    isso aqui nao se chama a fabrica: corre-se o `invoke`, e lê-se o que ficou
    **na fila**.
    """

    def _esvaziar(self, camada: Any) -> list[Any]:
        vagas = []
        while not camada._tomadas.empty():
            vagas.append(camada._tomadas.get_nowait())
        return vagas

    def test_as_vagas_da_fila_sao_distintas_e_veem_a_mesma_tabela(self) -> None:
        """Nos quatro tamanhos de *pool*, e **sem concorrencia**.

        A fila nasce com `quantas` vagas a `None` e cada invocacao devolve a
        ligacao ao **fim** da fila, pelo que `quantas` invocacoes em serie tiram
        os `quantas` `None` e enchem todas as vagas. E por isto que o criterio 2
        fecha numa corrida: nada aqui depende de duas *threads* se cruzarem.
        """
        caso = test_tls._Base("runTest")
        for quantas in POOLS:
            with self.subTest(pool=quantas):
                with mock.patch.dict(
                    os.environ, {VARIAVEL_DE_LIGACOES: str(quantas)}
                ):
                    camada, ligacao, _ = caso.camada()
                self.assertEqual(camada._quantas, quantas)

                for indice in range(quantas):
                    resultado = caso.invocar(
                        camada, idempotency_key=f"k-181-{indice}"
                    )
                    self.assertTrue(
                        resultado.ok, f"invocacao {indice}: {resultado.error}"
                    )

                vagas = self._esvaziar(camada)
                self.assertEqual(len(vagas), quantas)
                self.assertNotIn(None, vagas, "uma vaga ficou por encher")
                self.assertEqual(
                    len({id(vaga) for vaga in vagas}),
                    quantas,
                    "duas vagas da fila sao o mesmo objecto",
                )
                self.assertEqual(
                    len({id(vaga.idempotencia) for vaga in vagas}),
                    1,
                    "cada vaga ficou com a sua `tool_idempotency`",
                )
                # **Uma** entrada, e nao `quantas`: a chave da reserva deriva do
                # `cart_id` (§6.3) e nao do `idempotency_key` do pedido, pelo
                # que as `quantas` invocacoes do mesmo carrinho disputam a mesma
                # linha — que e precisamente o que serializa as cinquenta
                # confirmacoes. E a tabela onde ela esta e a que o ensaio tem na
                # mao: com uma tabela por vaga, esta fica a **zero**, porque
                # nenhuma vaga lhe escreveu.
                self.assertEqual(
                    len(ligacao.idempotencia),
                    1,
                    "a reserva das vagas nao aparece na tabela do ensaio",
                )


class TestOGuardaContinuaAMorder(unittest.TestCase):
    """Criterio 4 do KAM-181: a guarda nao foi tocada, e continua a morder.

    Mede-se **sem** *threads* de proposito: duas *threads* so levantam quando se
    cruzam, e o que aqui se afirma e a regra e nao a frequencia com que ela
    aparece. O `LIGACOES_POR_OMISSAO` tambem nao mudou, e isso lê-se aqui.
    """

    def test_a_mesma_ligacao_duas_vezes_levanta(self) -> None:
        ligacao = _Ligacao()
        with tenant_guard.tx(ligacao, TENANT):
            with self.assertRaises(tenant_guard.LigacaoEmUso):
                with tenant_guard.tx(ligacao, TENANT):
                    pass

    def test_duas_vagas_da_mesma_ligacao_nao_levantam(self) -> None:
        """E e o que torna a correccao do KAM-181 uma correccao e nao um atalho.

        Duas vagas sao dois objectos, logo duas entradas na `WeakSet` do guarda
        — que indexa pelo **objecto** e nao pelo endereco (KAM-163), e que
        `_Ligacao` nao perturba porque nao define `__eq__` nem `__hash__`.
        """
        ligacao = _Ligacao()
        with tenant_guard.tx(ligacao.nova_vaga(), TENANT):
            with tenant_guard.tx(ligacao.nova_vaga(), TENANT):
                pass
        # Duas transaccoes, dois `commit` — contados no **mesmo** estado.
        self.assertEqual(ligacao.commits, 2)

    def test_a_vaga_nao_define_igualdade(self) -> None:
        """A ressalva do KAM-163: com `__eq__`, duas vagas distintas colidiam."""
        vaga = _Ligacao().nova_vaga()
        self.assertIs(type(vaga).__eq__, object.__eq__)
        self.assertIs(type(vaga).__hash__, object.__hash__)

    def test_o_pool_por_omissao_continua_em_quatro(self) -> None:
        """Baixa-lo a 1 escondia o defeito e desligava o paralelismo do KAM-028."""
        self.assertEqual(LIGACOES_POR_OMISSAO, 4)


if __name__ == "__main__":
    unittest.main()
