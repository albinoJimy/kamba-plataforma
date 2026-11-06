"""«O resultado nao contem texto de mensagens» — medido por **forma do valor**.

O ticket pede, nos «Testes Requeridos», «um teste de que o resultado nao contem
texto de mensagens». Escrito ao pe da letra, esse teste faz-se em tres linhas e
**nao mede nada**:

    for chave in saida:
        assert chave not in ("body", "text", "caption")

Fica verde com uma mensagem inteira guardada num campo chamado `nota`, `fase` ou
`ref`. E o modo de falha desta classe de ensaio, e uma revisao adversarial
apanhou-o noutro ticket desta casa, num ensaio que olhava para nomes de etiqueta
em vez de olhar para a forma dos valores.

Por isso o que se mede aqui e a **forma de cada valor da saida**, com tres
detectores:

    telefone     os dois padroes canonicos de `tools/contract_diff/pii.py`,
                 mais a forma **local** `9########` que um cliente angolano
                 escreve e que nenhum dos dois apanha
    wamid        o prefixo `wamid.`, que em claro leva o numero do interlocutor
                 em base64 (`docs/logs.md` §2.1)
    texto livre  um valor com um caractere **fora do alfabeto estrutural**
                 `[A-Za-z0-9_:.-]`, ou com mais de 48 caracteres

## O canario, que e a metade que torna isto um ensaio

Um detector que devolva sempre zero passa `test_a_saida_nao_tem_nenhuma_das_tres_formas`
e deixa passar tudo. Logo os mesmos detectores correm primeiro **sobre a
entrada**, e tem de encontrar lá as tres formas. Sem este passo, o ensaio de cima
e uma afirmacao sobre o detector e nao sobre a saida.

É a mesma disciplina dos passos de canario dos gates 3b, 9 e 11 deste
repositorio: provar que o lint morde, antes de ler o verde dele.

## Os numeros deste ficheiro sao sinteticos e estao declarados

Os literais com forma de movel angolano sao sequenciais a partir do prefixo
movel e **nao pertencem a ninguem**. Estao declarados no `INVENTARIO` de
`tools/meta-sim/src/inventario.ts` com contagem exacta, que e o que o gate 7
exige — uma pasta isenta cresce em silencio, um inventario com contagem nao.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

# Os padroes canonicos, e nao uma quarta copia deles. `tools/` tem de estar no
# PYTHONPATH — ver o `__init__.py` desta pasta.
from contract_diff.pii import E164_ENTRE_ASPAS, TELEFONE_AO

from extrair import extrair
from registo import ConteudoRecusado, escrever, opaco, validar

#: O movel angolano com espaco. Casa `TELEFONE_AO` e **nao** casa
#: `E164_ENTRE_ASPAS`, porque o espaco quebra a corrida de digitos: 1 ocorrencia.
TELEFONE_COM_ESPACO = "+244 923456789"

#: O mesmo numero sem espaco. Casa os **dois** padroes — o segundo porque fica
#: entre aspas num literal de Python —, logo 2 ocorrencias para o gate 7.
TELEFONE_SEM_ESPACO = "+244923456789"

#: A forma **local**, que e a que um cliente angolano escreve no WhatsApp.
#: Nenhum dos dois padroes canonicos a apanha (um exige `244`, o outro um `+`), e
#: e por isso que o detector deste ficheiro acrescenta o terceiro: um telefone
#: que entrasse assim num ficheiro de evidencia passava o gate 7 e continuava a
#: ser um dado pessoal. 0 ocorrencias para o gate 7.
TELEFONE_LOCAL = "923456789"

#: Um `wamid` com a forma real. O base64 **nao** descodifica para numero nenhum:
#: e texto de ensaio, de proposito, para nao repetir a divida 51 de
#: `docs/dividas-documentais.md`, onde o base64 de uma *fixture* de outro ticket
#: descodifica para um movel angolano e o gate 7 nao o ve.
WAMID = "wamid.SElUT1JJQ09ERU5TQUlPREVIMzEyMw=="

#: Texto de conversa. E o que nao pode sobreviver a nenhum caminho.
TEXTO = "Bom dia, tem o vestido azul em tamanho M e quanto custa com entrega?"

#: A partir de quantos caracteres um valor se le como texto livre e nao como
#: identificador ou enumeracao.
LIMITE_DE_TEXTO = 48

#: Movel angolano na forma local: nove digitos a comecar em 9. A fronteira
#: `(?<!\d)`/`(?!\d)` evita apanhar uma janela de nove digitos **dentro** de um
#: numero maior — o defeito que a entrada do `test_minimizacao.py` do inventario
#: descreve, onde um `\d{9}` deslizante acusou quarenta e dois falsos.
TELEFONE_LOCAL_PADRAO = re.compile(r"(?<!\d)9[0-9]{8}(?!\d)")

#: O alfabeto de que **todos** os valores legitimos do registo sao feitos:
#: rotulos (`N1`), enumeracoes (`PARTNER_REMOVED`), nomes de campo
#: (`smb_app_state_sync`), fases (`fase_1`), resumos (`m_<32 hex>`) e carimbos
#: ISO (`2026-11-06T10:00:00.000Z`). Um caractere fora disto nao vem de nenhum
#: deles.
#:
#: E a definicao que resistiu: a primeira versao deste detector procurava
#: «pontuacao de frase» e acusava **o carimbo ISO**, pelos dois-pontos e pelo
#: ponto dos milissegundos. Um detector que grita sobre um valor legitimo e um
#: detector que alguem desliga.
FORA_DO_ALFABETO = re.compile(r"[^A-Za-z0-9_:.\-]")


def telefones(texto: str) -> list[str]:
    """As tres formas de telefone neste texto."""
    achados: list[str] = []
    for padrao in (TELEFONE_AO, E164_ENTRE_ASPAS, TELEFONE_LOCAL_PADRAO):
        achados.extend(m.group(0) for m in padrao.finditer(texto))
    return achados


def wamids(texto: str) -> list[str]:
    """Os `wamid` em claro neste texto."""
    return [m.group(0) for m in re.finditer(r"wamid\.[A-Za-z0-9+/=_-]*", texto)]


def texto_livre(valor: object) -> bool:
    """Se este **valor** se le como texto escrito por uma pessoa.

    Dois sinais, e qualquer um basta: um caractere fora do alfabeto estrutural —
    um espaco, um acento, um `+`, uma virgula — ou mais de `LIMITE_DE_TEXTO`
    caracteres. Nenhum identificador, carimbo, rotulo ou enumeracao do registo
    tem nenhum dos dois, o que torna isto uma medicao da **forma** e nao do nome.

    **O limite declarado:** uma palavra unica, curta e sem acento (`sim`) nao e
    apanhada. Nao e descuido — e o preco de medir forma em vez de semantica —, e
    o que fecha esse caminho e a outra metade: para um `sim` chegar ao ficheiro
    tinha de passar pela *allowlist* de `registo.PERMITIDOS`, que so admite as
    dezassete chaves e as formas delas.
    """
    if type(valor) is not str:
        return False
    return len(valor) > LIMITE_DE_TEXTO or FORA_DO_ALFABETO.search(valor) is not None


def valores(arvore: object) -> list[object]:
    """Todos os valores-folha de uma arvore, **e tambem as chaves**.

    As chaves entram porque uma chave tambem e texto que vai para o ficheiro, e
    um corpo hostil pode trazer conteudo numa chave. Nenhum dos detectores
    distingue os dois casos, nem precisa.
    """
    saida: list[object] = []
    if isinstance(arvore, dict):
        for chave, valor in arvore.items():
            saida.append(chave)
            saida.extend(valores(valor))
    elif isinstance(arvore, list):
        for item in arvore:
            saida.extend(valores(item))
    else:
        saida.append(arvore)
    return saida


def corpo_hostil() -> dict:
    """Um corpo de webhook com as tres formas em **sitios diferentes**.

    Inclui de proposito o caso que um ensaio por nome de campo nao apanha: o
    mesmo texto de conversa tambem num campo chamado `fase` e numa chave
    inventada `ref`, que **nao** sao nomes de campo de conteudo.
    """
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1" * 15,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": TELEFONE_COM_ESPACO,
                                "phone_number_id": "900900900900900",
                            },
                            "contacts": [
                                {"profile": {"name": "Loja da Dona Ana"},
                                 "wa_id": TELEFONE_SEM_ESPACO}
                            ],
                            "messages": [
                                {
                                    "id": WAMID,
                                    "from": TELEFONE_SEM_ESPACO,
                                    "timestamp": "1790812800",
                                    "type": "text",
                                    "text": {"body": TEXTO},
                                    # Os dois campos que um ensaio por nome de
                                    # campo deixa passar:
                                    "fase": TEXTO,
                                    "ref": TELEFONE_LOCAL,
                                }
                            ],
                        },
                    },
                    {
                        "field": "smb_app_state_sync",
                        "value": {
                            "metadata": {"phone_number_id": "900900900900900"},
                            "state_sync": [
                                {
                                    "type": "contact",
                                    "action": "add",
                                    "metadata": {"phase": 1},
                                    "contact": {
                                        "full_name": "Ana Maria dos Santos",
                                        "phone_number": TELEFONE_LOCAL,
                                    },
                                }
                            ],
                        },
                    },
                ],
            }
        ],
    }


ROTULOS = {"900900900900900": "N1"}


class TestCanario(unittest.TestCase):
    """Os detectores encontram, na **entrada**, o que ha para encontrar.

    Sem esta classe, `TestSaida` e uma afirmacao sobre o detector.
    """

    def setUp(self) -> None:
        self.bruto = json.dumps(corpo_hostil(), ensure_ascii=False)

    def test_o_detector_de_telefone_ve_as_tres_formas(self) -> None:
        achados = telefones(self.bruto)
        self.assertTrue(
            any(TELEFONE_COM_ESPACO in a for a in achados),
            "o detector nao ve a forma com espaco",
        )
        self.assertTrue(
            any(a.strip('"') == TELEFONE_SEM_ESPACO for a in achados),
            "o detector nao ve a forma sem espaco",
        )
        self.assertIn(
            TELEFONE_LOCAL, achados, "o detector nao ve a forma local de nove digitos"
        )

    def test_o_detector_de_wamid_ve_o_wamid(self) -> None:
        self.assertIn(WAMID, wamids(self.bruto))

    def test_o_detector_de_texto_livre_ve_o_texto(self) -> None:
        self.assertTrue(texto_livre(TEXTO))
        # E nao grita sobre o que e legitimo na saida, senao era inutil.
        for legitimo in ("N1", "messages", "entrada", "PARTNER_REMOVED",
                         "fase_1", "smb_app_state_sync", "m_" + "0" * 32,
                         "2026-11-06T10:00:00.000Z"):
            with self.subTest(valor=legitimo):
                self.assertFalse(
                    texto_livre(legitimo),
                    f"{legitimo!r} e um valor legitimo do registo e foi acusado",
                )

    def test_a_forma_local_escapa_aos_padroes_canonicos(self) -> None:
        """A razao de haver um terceiro padrao, medida e nao assumida."""
        self.assertIsNone(TELEFONE_AO.search(TELEFONE_LOCAL))
        self.assertIsNone(E164_ENTRE_ASPAS.search(f'"{TELEFONE_LOCAL}"'))
        self.assertIsNotNone(TELEFONE_LOCAL_PADRAO.search(TELEFONE_LOCAL))


class TestSaida(unittest.TestCase):
    """Nenhuma das tres formas sobrevive ao caminho `extrair` -> `escrever`."""

    def setUp(self) -> None:
        self.linhas = extrair(
            corpo_hostil(), ROTULOS, nossos=(), recebido_em="2026-11-06T10:00:00.000Z"
        )

    def test_houve_saida(self) -> None:
        """O controlo: zero linhas tornava tudo o que vem a seguir vacuo."""
        self.assertGreater(len(self.linhas), 0, "o corpo hostil nao produziu linhas")

    def test_a_saida_nao_tem_nenhuma_das_tres_formas(self) -> None:
        texto = json.dumps(self.linhas, ensure_ascii=False)
        self.assertEqual(telefones(texto), [], "um telefone sobreviveu a extraccao")
        self.assertEqual(wamids(texto), [], "um wamid em claro sobreviveu")
        acusados = [v for v in valores(self.linhas) if texto_livre(v)]
        self.assertEqual(acusados, [], "um valor com forma de texto livre sobreviveu")

    def test_o_ficheiro_escrito_tambem_nao_as_tem(self) -> None:
        """A mesma medicao sobre os **bytes no disco**, que e o artefacto real.

        Mede-se outra vez porque `escrever` serializa, e e a serializacao que
        pode reintroduzir o que a arvore nao tinha — um `ensure_ascii` ao
        contrario, um separador, um `repr`. O ficheiro e que fica.
        """
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / "eventos.jsonl"
            for linha in self.linhas:
                escrever(destino, linha)
            bruto = destino.read_text(encoding="ascii")
        self.assertGreater(len(bruto.strip().splitlines()), 0)
        self.assertEqual(telefones(bruto), [])
        self.assertEqual(wamids(bruto), [])
        for linha in bruto.strip().splitlines():
            for valor in valores(json.loads(linha)):
                self.assertFalse(texto_livre(valor), f"texto livre no disco: {valor!r}")

    def test_o_texto_da_conversa_nao_aparece_em_sitio_nenhum(self) -> None:
        """A busca literal, que e o que o ticket pede a letra.

        Fica **depois** das medicoes por forma e nao antes: e mais fraca — um
        texto diferente passava — e sozinha era o ensaio tautologico que esta
        classe existe para nao ser.
        """
        texto = json.dumps(self.linhas, ensure_ascii=False)
        for fragmento in (TEXTO, "vestido", "Dona Ana", "Ana Maria"):
            with self.subTest(fragmento=fragmento):
                self.assertNotIn(fragmento, texto)


class TestAllowlist(unittest.TestCase):
    """A guarda do `registo`: chave fora da lista, ou valor fora da forma."""

    def test_chave_desconhecida_e_recusada(self) -> None:
        with self.assertRaises(ConteudoRecusado):
            validar({"tipo": "messages", "ref": "x"})

    def test_texto_de_conversa_num_campo_permitido_e_recusado(self) -> None:
        """O caso exacto que um ensaio por nome de campo deixa passar.

        `fase` **esta** na *allowlist*. O que a recusa e a forma do valor.
        """
        for chave in ("fase", "tipo", "evento", "razao", "direccao"):
            with self.subTest(chave=chave):
                with self.assertRaises(ConteudoRecusado):
                    validar({chave: TEXTO})

    def test_telefone_no_campo_do_rotulo_e_recusado(self) -> None:
        for valor in (TELEFONE_COM_ESPACO, TELEFONE_SEM_ESPACO, TELEFONE_LOCAL):
            with self.subTest(valor=valor[:6]):
                with self.assertRaises(ConteudoRecusado):
                    validar({"numero": valor})

    def test_wamid_em_claro_no_campo_do_id_e_recusado(self) -> None:
        with self.assertRaises(ConteudoRecusado):
            validar({"id": WAMID})

    def test_booleano_nao_passa_por_contagem(self) -> None:
        """`True` e um `int` em Python; `type(v) is int` e que o recusa."""
        with self.assertRaises(ConteudoRecusado):
            validar({"contactos": True})

    def test_carimbo_fora_da_gama_e_recusado(self) -> None:
        for valor in (0, 1, 10**12, -1):
            with self.subTest(valor=valor):
                with self.assertRaises(ConteudoRecusado):
                    validar({"carimbo": valor})

    def test_uma_linha_legitima_passa(self) -> None:
        """O controlo da *allowlist*: se nada passasse, nao provava nada."""
        linha = {
            "tipo": "smb_message_echoes",
            "numero": "N2",
            "recebido_em": "2026-11-06T10:00:00.000Z",
            "carimbo": 1_790_812_800,
            "id": "m_" + "a" * 32,
            "direccao": "echo",
            "enviada_por_nos": False,
        }
        self.assertEqual(validar(linha), linha)


class TestFormaDaFase(unittest.TestCase):
    """Regressao: `fase` era a unica chave que admitia digitos, e admitia-os todos.

    A forma de entao (`[a-z][a-z0-9_]{0,31}`) aceitava `fase_923456789` e
    `fase_244923456789` — um movel angolano em claro pela chave que a allowlist
    declarava fechar o caminho. Mede-se aqui pela **forma**, e no
    `test_extrair.py` pelo caminho que a produzia.
    """

    def test_um_telefone_na_fase_e_recusado(self) -> None:
        for sufixo in (TELEFONE_LOCAL, "244923456789", "00244923456789", "923456788"):
            with self.subTest(sufixo=sufixo[:8]):
                with self.assertRaises(ConteudoRecusado):
                    validar({"fase": f"fase_{sufixo}"})

    def test_as_fases_da_meta_passam(self) -> None:
        """O controlo: a Meta manda 0 e 1, e ha nomes de fase em letras."""
        for boa in ("fase_0", "fase_1", "fase_99", "initial_sync", "a"):
            with self.subTest(fase=boa):
                self.assertEqual(validar({"fase": boa}), {"fase": boa})

    def test_uma_corrida_de_digitos_longa_e_recusada(self) -> None:
        for ma in ("fase_100", "fase_1234567890", "a1234567890", "fase_0_923456789"):
            with self.subTest(fase=ma):
                with self.assertRaises(ConteudoRecusado):
                    validar({"fase": ma})


class TestContagemDaAllowlist(unittest.TestCase):
    """A contagem de chaves **conta-se**, e nao se cita.

    Regressao: quatro sitios afirmavam «17 chaves» e a allowlist tinha 18 — a
    contagem que sustenta a justificacao do criterio 6, num ticket cuja tese e
    que as contagens se medem. A chave que faltava na conta era precisamente a
    que tinha o defeito do `TestFormaDaFase`.
    """

    def test_sao_dezoito(self) -> None:
        from registo import PERMITIDOS

        self.assertEqual(len(PERMITIDOS), 18)

    def test_toda_a_chave_tem_forma_e_descricao(self) -> None:
        from registo import PERMITIDOS

        for chave, forma in PERMITIDOS.items():
            with self.subTest(chave=chave):
                self.assertTrue(callable(forma.aceita))
                self.assertTrue(forma.descricao.strip())


class TestIdOpaco(unittest.TestCase):
    def test_recusa_um_valor_so_de_digitos(self) -> None:
        """`docs/logs.md` §2.1: um espaco pequeno inverte-se por enumeracao."""
        for valor in (TELEFONE_LOCAL, TELEFONE_SEM_ESPACO, TELEFONE_COM_ESPACO,
                      "244923456789", "00244923456789"):
            with self.subTest(valor=valor[:8]):
                with self.assertRaises(ConteudoRecusado):
                    opaco(valor)

    def test_recusa_as_outras_grafias_de_separador(self) -> None:
        """Regressao: a guarda retirava so o espaco, e conhecia uma de quatro.

        `244-923-456-789` e `(244) 923456789` eram **resumidos** em vez de
        descartados, e um resumo sem chave de um espaco de 10^8 inverte-se por
        enumeracao — que e a razao de o ADR-010 mandar descartar.
        """
        for valor in ("244-923-456-789", "(244) 923456789", "244.923456789",
                      "+244 923 456 789", "244/923456789", "244 923-456.789"):
            with self.subTest(valor=valor[:10]):
                with self.assertRaises(ConteudoRecusado):
                    opaco(valor)

    def test_resume_um_wamid(self) -> None:
        saida = opaco(WAMID)
        self.assertRegex(saida, r"^m_[0-9a-f]{32}$")
        self.assertNotIn("wamid", saida)

    def test_o_resumo_e_estavel(self) -> None:
        """Serve para **correlacionar**: duas execucoes dao o mesmo valor."""
        self.assertEqual(opaco(WAMID), opaco(WAMID))


if __name__ == "__main__":
    unittest.main()
