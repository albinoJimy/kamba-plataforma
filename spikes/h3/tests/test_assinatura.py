"""O `X-Hub-Signature-256` sobre o corpo bruto (KAM-100, «Testes Requeridos»).

O ticket pede «assinatura valida e invalida, corpo bruto». Os dois primeiros sao
directos; o terceiro e o que exige desenho, porque **um ensaio que so assine e
verifique o mesmo objecto passa tanto na implementacao certa como na errada**.

A implementacao errada e `hmac(json.dumps(json.loads(corpo)))`. Ela calcula a
assinatura sobre uma forma canonica, pelo que:

    assinar(corpo) -> verificar(corpo)                  passa nas duas
    assinar(corpo) -> verificar(outros_bytes_mesma_arvore)  passa SO na errada

E a segunda linha que distingue as duas, e e ela que esta no
`TestCorpoBruto`. Sem ela, os ensaios ficavam verdes com o *fail-open* la dentro.
"""

from __future__ import annotations

import json
import unittest

from assinatura import (
    CABECALHO,
    PREFIXO,
    VARIAVEL_DO_SEGREDO,
    AssinaturaInvalida,
    SegredoEmFalta,
    calcular,
    segredo,
    verificar,
)

#: A chave dos ensaios. Nao e o App Secret de ninguem: e texto de ensaio, e o
#: App Secret real vive no cofre e entra por ambiente.
CHAVE = b"segredo-de-ensaio-do-spike-h3"


class TestValidaEInvalida(unittest.TestCase):
    def test_assinatura_valida_passa(self) -> None:
        corpo = b'{"object":"whatsapp_business_account","entry":[]}'
        verificar(corpo, calcular(corpo, CHAVE), CHAVE)

    def test_assinatura_de_outro_corpo_e_recusada(self) -> None:
        corpo = b'{"a":1}'
        outro = b'{"a":2}'
        with self.assertRaises(AssinaturaInvalida):
            verificar(corpo, calcular(outro, CHAVE), CHAVE)

    def test_assinatura_com_outra_chave_e_recusada(self) -> None:
        corpo = b'{"a":1}'
        with self.assertRaises(AssinaturaInvalida):
            verificar(corpo, calcular(corpo, b"outra-chave"), CHAVE)

    def test_um_bit_trocado_na_assinatura_e_recusado(self) -> None:
        """A alteracao minima possivel, para que o ensaio nao viva de margem."""
        corpo = b'{"a":1}'
        bom = calcular(corpo, CHAVE)
        ultimo = bom[-1]
        trocado = bom[:-1] + ("0" if ultimo != "0" else "1")
        with self.assertRaises(AssinaturaInvalida):
            verificar(corpo, trocado, CHAVE)

    def test_sem_cabecalho_e_recusado(self) -> None:
        for ausente in (None, ""):
            with self.subTest(cabecalho=ausente):
                with self.assertRaises(AssinaturaInvalida):
                    verificar(b'{"a":1}', ausente, CHAVE)

    def test_sem_prefixo_e_recusado(self) -> None:
        """Um `sha1=` ou um hex nu nao e um `X-Hub-Signature-256`."""
        corpo = b'{"a":1}'
        sem = calcular(corpo, CHAVE)[len(PREFIXO) :]
        for cabecalho in (sem, "sha1=" + sem, "SHA256=" + sem):
            with self.subTest(cabecalho=cabecalho[:12]):
                with self.assertRaises(AssinaturaInvalida):
                    verificar(corpo, cabecalho, CHAVE)

    def test_corpo_vazio_assinado_passa(self) -> None:
        """Um corpo vazio e assinavel, e o receptor recusa-o pelo tamanho.

        A recusa de um corpo vazio e politica do transporte (`LIMITE_DO_CORPO`),
        nao da assinatura. Separa-se de proposito: uma funcao de verificacao que
        tambem decidisse tamanhos tinha duas razoes para dizer «nao».
        """
        verificar(b"", calcular(b"", CHAVE), CHAVE)


class TestCorpoBruto(unittest.TestCase):
    """O ensaio que distingue a implementacao certa da que re-serializa.

    Cada caso e um par de cadeias de bytes **diferentes** que descodificam para a
    **mesma** arvore. A assinatura do primeiro nao pode validar o segundo.
    """

    #: Pares `(assinado, variante)`: bytes diferentes, arvore igual.
    PARES = (
        # Ordem das chaves.
        (b'{"a":1,"b":2}', b'{"b":2,"a":1}'),
        # Espacos entre os tokens.
        (b'{"a":1,"b":2}', b'{"a": 1, "b": 2}'),
        # Escape de nao-ASCII: `á` e o mesmo caractere que `a` acentuado.
        (b'{"t":"\\u00e1"}', '{"t":"á"}'.encode("utf-8")),
        # Um `+` num numero, que o descodificador de JSON de Python aceita no
        # expoente.
        (b'{"n":1e2}', b'{"n":1E2}'),
        # Espaco em branco a volta do objecto.
        (b'{"a":1}', b'  {"a":1}\n'),
    )

    def test_a_arvore_e_a_mesma_nos_pares(self) -> None:
        """O controlo do ensaio: se as arvores diferissem, nao provava nada.

        Sem isto, um par mal escrito — duas arvores diferentes — tornava o ensaio
        seguinte trivial, porque uma assinatura de outro corpo e recusada por
        qualquer implementacao. E a mesma classe de defeito que o `canario` dos
        portoes desta casa existe para fechar.
        """
        for assinado, variante in self.PARES:
            with self.subTest(par=assinado[:20]):
                self.assertNotEqual(assinado, variante, "os bytes tem de diferir")
                self.assertEqual(
                    json.loads(assinado),
                    json.loads(variante),
                    "a arvore tem de ser a mesma, senao o ensaio e trivial",
                )

    def test_variante_com_a_mesma_arvore_e_recusada(self) -> None:
        """**Este e o ensaio do corpo bruto.**

        Numa implementacao que re-serializasse, cada um destes casos passava — e
        e isso o *fail-open*: uma assinatura capturada autenticava toda a familia
        de bytes com aquela arvore.
        """
        for assinado, variante in self.PARES:
            with self.subTest(par=assinado[:20]):
                cabecalho = calcular(assinado, CHAVE)
                with self.assertRaises(AssinaturaInvalida):
                    verificar(variante, cabecalho, CHAVE)

    def test_a_implementacao_que_reserializa_passaria(self) -> None:
        """A prova de que o ensaio acima nao e vacuo.

        Escreve-se aqui a implementacao **errada** e mostra-se que ela aceita
        todos os pares. Sem isto, `test_variante_com_a_mesma_arvore_e_recusada`
        podia estar a passar por uma razao qualquer — um par invalido, uma
        excepcao vinda de outro sitio — em vez de medir o predicado.
        """
        import hashlib
        import hmac

        def canonico(corpo: bytes) -> bytes:
            return json.dumps(json.loads(corpo), sort_keys=True).encode("utf-8")

        def assinar_errado(corpo: bytes, chave: bytes) -> str:
            resumo = hmac.new(chave, canonico(corpo), hashlib.sha256).hexdigest()
            return PREFIXO + resumo

        def verificar_errado(corpo: bytes, cabecalho: str, chave: bytes) -> bool:
            return hmac.compare_digest(cabecalho, assinar_errado(corpo, chave))

        for assinado, variante in self.PARES:
            with self.subTest(par=assinado[:20]):
                self.assertTrue(
                    verificar_errado(variante, assinar_errado(assinado, CHAVE), CHAVE),
                    "a implementacao errada tinha de aceitar a variante; se nao "
                    "aceita, o par nao demonstra o fail-open",
                )

    def test_recusa_str(self) -> None:
        """Um `str` nao tem bytes: a codificacao seria uma escolha escondida."""
        with self.assertRaises(TypeError):
            verificar('{"a":1}', "sha256=0" * 1, CHAVE)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            calcular('{"a":1}', CHAVE)  # type: ignore[arg-type]

    def test_corpo_invalido_mas_assinado_valida(self) -> None:
        """A **ordem**: a assinatura verifica-se sem o descodificador correr.

        Um corpo correctamente assinado que nao e JSON valido tem de passar a
        verificacao. Numa implementacao que descodificasse primeiro, isto
        levantava `JSONDecodeError` — e o descodificador teria corrido sobre
        bytes nao autenticados, que e a superficie de ataque maior que aqui ha.
        """
        for lixo in (b"{nao e json", b"\xff\xfe\x00", b"[1,2,", b"null"):
            with self.subTest(corpo=lixo[:10]):
                verificar(lixo, calcular(lixo, CHAVE), CHAVE)


class TestSegredo(unittest.TestCase):
    def test_sem_variavel_levanta(self) -> None:
        import os

        anterior = os.environ.pop(VARIAVEL_DO_SEGREDO, None)
        try:
            with self.assertRaises(SegredoEmFalta):
                segredo()
            os.environ[VARIAVEL_DO_SEGREDO] = ""
            with self.assertRaises(SegredoEmFalta):
                segredo()
        finally:
            os.environ.pop(VARIAVEL_DO_SEGREDO, None)
            if anterior is not None:
                os.environ[VARIAVEL_DO_SEGREDO] = anterior

    def test_a_variavel_lida_e_a_declarada(self) -> None:
        import os

        anterior = os.environ.get(VARIAVEL_DO_SEGREDO)
        os.environ[VARIAVEL_DO_SEGREDO] = "abc"
        try:
            self.assertEqual(segredo(), b"abc")
        finally:
            if anterior is None:
                os.environ.pop(VARIAVEL_DO_SEGREDO, None)
            else:
                os.environ[VARIAVEL_DO_SEGREDO] = anterior

    def test_verificar_sem_chave_usa_o_ambiente(self) -> None:
        """O caminho por omissao: `chave=None` vai ao ambiente."""
        import os

        anterior = os.environ.get(VARIAVEL_DO_SEGREDO)
        os.environ[VARIAVEL_DO_SEGREDO] = "abc"
        try:
            corpo = b'{"a":1}'
            verificar(corpo, calcular(corpo, b"abc"))
            with self.assertRaises(AssinaturaInvalida):
                verificar(corpo, calcular(corpo, b"outra"))
        finally:
            if anterior is None:
                os.environ.pop(VARIAVEL_DO_SEGREDO, None)
            else:
                os.environ[VARIAVEL_DO_SEGREDO] = anterior

    def test_o_nome_do_cabecalho_e_o_da_meta(self) -> None:
        self.assertEqual(CABECALHO, "X-Hub-Signature-256")
        self.assertEqual(PREFIXO, "sha256=")

    def test_uma_chave_vazia_explicita_e_recusada(self) -> None:
        """Regressao: `b""` nao e `None`, e saltava a guarda do segredo.

        O docstring do modulo afirma que um segredo vazio aceita o que qualquer
        pessoa assine com um segredo vazio. Era verdade para o caminho do
        receptor — que passa `segredo()`, e esse levanta — e **falso** para a
        funcao, que e a parte reutilizavel e a que os ensaios exercitam.
        """
        corpo = b'{"a":1}'
        with self.assertRaises(SegredoEmFalta):
            verificar(corpo, calcular(corpo, b""), b"")


class TestCabecalhoNaoAscii(unittest.TestCase):
    """Regressao: um byte > 0x7F no cabecalho derrubava a ligacao sem resposta.

    O `http.server` descodifica os cabecalhos em latin-1, e o `compare_digest`
    levanta `TypeError` sobre um `str` nao-ASCII — que **nao** e
    `AssinaturaInvalida`, pelo que o `do_POST` nao o apanhava e a ligacao caia
    sem o 4xx que `E1` §5 pede. Um HMAC em hexadecimal e ASCII por definicao.
    """

    def test_um_cabecalho_nao_ascii_e_assinatura_invalida(self) -> None:
        corpo = b'{"a":1}'
        for mau in (PREFIXO + "á" * 64, PREFIXO + "ÿ" + "0" * 63,
                    PREFIXO + "€"):
            with self.subTest(cabecalho=repr(mau[:12])):
                with self.assertRaises(AssinaturaInvalida):
                    verificar(corpo, mau, CHAVE)

    def test_nao_levanta_type_error(self) -> None:
        """O que importa e **qual** a excepcao: o receptor so apanha uma delas."""
        corpo = b'{"a":1}'
        try:
            verificar(corpo, PREFIXO + "á" * 64, CHAVE)
        except AssinaturaInvalida:
            pass
        except TypeError as e:  # pragma: no cover
            self.fail(f"levantou TypeError, que o receptor nao apanha: {e}")


if __name__ == "__main__":
    unittest.main()
