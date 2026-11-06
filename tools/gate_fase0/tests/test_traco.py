"""O traço, e o controlo negativo que vale mais do que o caminho feliz (KAM-108).

Os «Testes Requeridos» do bloco pedem «teste do *script* de traço com *logs*
sintéticos (não deve emitir conteúdo ou telefone)». Isso é um **controlo
negativo**, e a diferença não é de vocabulário: um ensaio que alimente o traço
com entradas limpas e confirme que a saída está limpa fica verde com todas as
guardas apagadas. O que mede o predicado é alimentá-lo com uma entrada que
**tem** conteúdo e telefone e provar que a saída não os leva.

## Onde está o telefone deste ficheiro, e porque não está escrito

O número de forma real do controlo negativo **monta-se em execução** —
`"+244 9" + oito dígitos` — e não aparece como literal em sítio nenhum. São duas
consequências, e as duas são deliberadas:

1. **O detector é exercitado com um número de forma real**, que é o que importa:
   o `tools/meta-sim/src/inventario.ts` diz por extenso que «um redactor testado
   só com números do `999` nunca prova que apanha um `+244 9…`».
2. **A árvore não ganha um literal com forma de telefone**, pelo que o varrimento
   do *gate* 7 não muda e o `INVENTARIO` não leva entrada nova. Medido: 35
   ficheiros e 124 ocorrências antes e depois destes ficheiros, idênticas ficheiro
   a ficheiro. A alternativa — escrever o número e declará-lo no inventário — era
   legítima e tem precedente (KAM-100, 5 ocorrências num ficheiro), mas o
   `INVENTARIO` recusa entradas mortas e exige contagem exacta, e uma entrada que
   não precisa de existir é mais uma superfície a manter a par do par fixado do
   `inventario.test.ts` — que `pnpm` não corre nesta máquina.

Isto **não** é fugir ao portão: o portão proíbe números reais na árvore, e aqui
não entra nenhum. O que entra é um valor que existe durante a execução do ensaio
e nunca é escrito.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gate_fase0 import traco

TENANT = "0b6f1d2e-3c4a-4b5c-8d9e-0f1a2b3c4d5e"
PEDIDO = "11111111-2222-4333-8444-555555555555"
EVENTO = "66666666-7777-4888-8999-aaaaaaaaaaaa"
MARCACAO = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"
MENSAGEM = "m_" + "0123456789abcdef" * 2


def movel_de_forma_real() -> str:
    """Um número com a forma `+244 9` e oito dígitos, montado e nunca escrito.

    Ver o docstring do módulo. Os oito dígitos são sequenciais de propósito: não
    são de ninguém, e um sequencial é a escolha que o `numeros.ts` já faz para o
    intervalo fictício — o que muda aqui é só o indicativo, que é o que o
    detector tem de reconhecer.
    """
    return "+244 " + "9" + "12345678"


def conteudo_de_conversa() -> str:
    """Uma frase com espaços e acentos: o que o terceiro detector tem de apanhar."""
    return "bom dia, queria dois pães e uma água, pode ser?"


def _escrever(pasta: Path, nome: str, linhas: list[dict]) -> Path:
    caminho = pasta / nome
    caminho.write_bytes(
        ("\n".join(json.dumps(linha, ensure_ascii=False) for linha in linhas) + "\n")
        .encode("utf-8")
    )
    return caminho


def cadeia_limpa() -> list[dict]:
    """As quatro linhas de uma execução completa, só com identificadores."""
    return [
        {"tenant_id": TENANT, "msg_id": MENSAGEM, "ts": "2026-11-06T09:00:00.000Z"},
        {
            "tenant_id": TENANT,
            "turn_id": MENSAGEM,
            "entity": "encomenda",
            "entity_id": PEDIDO,
            "criado_at": "2026-11-06T09:01:00Z",
        },
        {
            "tenant_id": TENANT,
            "event_id": EVENTO,
            "tipo": "payment.manual_confirmed",
            "versao": 1,
            "agregado_tipo": "encomenda",
            "agregado_id": PEDIDO,
            "ocorrido_em": "2026-11-06T09:05:00Z",
        },
        {
            "tenant_id": TENANT,
            "consumer": "agr_servicos",
            "event_id": EVENTO,
            "agregado_tipo": "encomenda",
            "agregado_id": PEDIDO,
            "processado_at": "2026-11-06T09:05:01Z",
        },
    ]


class TestOsDetectoresMordem(unittest.TestCase):
    """O canário: sem isto, um detector que devolvesse zero passava tudo."""

    def test_o_detector_apanha_o_movel_angolano(self) -> None:
        disparados = traco.detectar(movel_de_forma_real())
        self.assertIn("telefone_ao", disparados)

    def test_o_detector_apanha_o_e164_entre_aspas(self) -> None:
        """A forma em que um telefone aparece num JSON: entre aspas e com `+`.

        O valor monta-se, como o do `movel_de_forma_real` e pela mesma razão —
        escrito como literal, `"+2449…"` casava os **dois** padrões do
        varrimento do *gate* 7 e este ficheiro passava a precisar de entrada no
        `INVENTARIO`. Medido: com o literal dava duas ocorrências aqui.
        """
        sem_espaco = movel_de_forma_real().replace(" ", "")
        disparados = traco.detectar(json.dumps({"x": sem_espaco}))
        self.assertIn("e164_entre_aspas", disparados)
        self.assertIn("telefone_ao", disparados)

    def test_o_detector_apanha_o_movel_local_de_nove_digitos(self) -> None:
        """A forma que nenhum dos dois padrões canónicos apanha.

        É o terceiro detector do KAM-100, e sem ele um `912345678` nu passava —
        e num ficheiro de evidência continuaria a ser um dado pessoal.
        """
        nu = "9" + "12345678"
        self.assertEqual(traco.detectar(nu), ["movel_local"])

    def test_o_detector_nao_dispara_num_uuid(self) -> None:
        """O par positivo, e não é decoração.

        Um detector que disparasse sobre um UUID punha o traço a recusar a sua
        própria saída, e o modo de falha seria indistinguível de uma fuga.
        """
        self.assertEqual(traco.detectar(TENANT), [])

    def test_o_detector_nao_dispara_num_id_opaco(self) -> None:
        self.assertEqual(traco.detectar(MENSAGEM), [])

    def test_o_intervalo_ficticio_dispara_e_e_dito(self) -> None:
        """Um `999…` **também** dispara, e isso é uma propriedade e não um bug.

        O varrimento do *gate* 7 desconta o intervalo fictício; este detector
        não, porque aqui a pergunta é outra: o traço não emite telefone nenhum,
        nem fictício. Fica medido para que ninguém leia o `999` como permitido.
        """
        self.assertEqual(traco.detectar('"+999123456789"'), ["e164_entre_aspas"])


class TestOControloNegativo(unittest.TestCase):
    """A entrada tem conteúdo e telefone; a saída não pode levar nenhum."""

    def setUp(self) -> None:
        self.pasta = TemporaryDirectory()
        self.raiz = Path(self.pasta.name)
        self.addCleanup(self.pasta.cleanup)
        self.sujas = cadeia_limpa()
        # As quatro formas em que isto chega na vida real, uma por linha:
        # um campo de texto livre, um telefone num campo que não existe na lista,
        # o telefone dentro de uma estrutura, e um campo com nome inocente.
        self.sujas[0]["texto"] = conteudo_de_conversa()
        self.sujas[1]["telefone"] = movel_de_forma_real()
        self.sujas[2]["cliente"] = {"wa_id": movel_de_forma_real()}
        self.sujas[3]["nota"] = f"{conteudo_de_conversa()} {movel_de_forma_real()}"
        self.entrada = _escrever(self.raiz, "sujo.jsonl", self.sujas)

    def test_a_entrada_tem_mesmo_conteudo_e_telefone(self) -> None:
        """Primeiro sobre a **entrada**, como canário.

        É a metade que o KAM-100 teve de acrescentar: sem ela, este ensaio ficava
        verde com uma entrada que não tinha nada para fugir.
        """
        bruto = self.entrada.read_text(encoding="utf-8")
        self.assertTrue(traco.detectar(bruto), "a entrada não tem telefone nenhum")
        self.assertTrue(
            traco.FORA_DO_ALFABETO.search(conteudo_de_conversa()),
            "a entrada não tem texto livre nenhum",
        )

    def test_a_saida_em_json_nao_leva_telefone_nem_conteudo(self) -> None:
        cadeias, descartes = traco.tracar([self.entrada])
        saida = traco.como_json(cadeias, descartes)
        self.assertEqual(traco.detectar(saida), [])
        self.assertNotIn(conteudo_de_conversa(), saida)
        self.assertNotIn("912345678", saida)

    def test_a_saida_em_texto_nao_leva_telefone_nem_conteudo(self) -> None:
        cadeias, _ = traco.tracar([self.entrada])
        saida = traco.como_texto(cadeias)
        self.assertEqual(traco.detectar(saida), [])
        self.assertNotIn(conteudo_de_conversa(), saida)

    def test_as_quatro_chaves_sujas_ficam_descartadas_e_contadas(self) -> None:
        """Descartadas **e contadas**: um descarte calado é uma fuga que ninguém vê.

        A contagem é o que diz ao operador que a entrada traz campos a mais — e
        se um dia trouxer um que devia estar na cadeia, é aqui que aparece.
        """
        _, descartes = traco.tracar([self.entrada])
        chaves = sorted(descarte.chave for descarte in descartes)
        self.assertEqual(chaves, ["cliente", "nota", "telefone", "texto"])

    def test_a_razao_do_descarte_nao_leva_o_valor(self) -> None:
        """A razão vai para a saída; se levasse o valor, levava o telefone."""
        _, descartes = traco.tracar([self.entrada])
        for descarte in descartes:
            self.assertEqual(traco.detectar(descarte.razao), [])
            self.assertNotIn(conteudo_de_conversa(), descarte.razao)

    def test_a_cadeia_fecha_apesar_de_a_entrada_estar_suja(self) -> None:
        """A limpeza não pode custar o traço: a cadeia é a mesma."""
        cadeias, _ = traco.tracar([self.entrada])
        self.assertEqual(len(cadeias), 1)
        self.assertTrue(cadeias[0].completa(), cadeias[0].em_falta)


class TestAGuardaDaForma(unittest.TestCase):
    """A segunda barreira: a forma do valor, e não o nome da chave."""

    def setUp(self) -> None:
        self.pasta = TemporaryDirectory()
        self.raiz = Path(self.pasta.name)
        self.addCleanup(self.pasta.cleanup)

    def test_um_telefone_numa_chave_de_elo_faz_a_leitura_falhar(self) -> None:
        """É o defeito do KAM-100: a chave da *allowlist* que admitia dígitos.

        Aqui o `order_id` exige UUID, pelo que um telefone lá dentro não passa a
        guarda — e **falha alto** em vez de perder a chave, porque um `order_id`
        a menos é uma cadeia que se cala sobre o pedido que existiu.
        """
        linhas = [{"tenant_id": TENANT, "order_id": movel_de_forma_real()}]
        caminho = _escrever(self.raiz, "elo.jsonl", linhas)
        with self.assertRaises(traco.ConteudoRecusado) as apanhado:
            traco.tracar([caminho])
        self.assertIn("order_id", str(apanhado.exception))

    def test_a_excepcao_nao_leva_o_valor_recusado(self) -> None:
        linhas = [{"tenant_id": TENANT, "order_id": movel_de_forma_real()}]
        caminho = _escrever(self.raiz, "elo.jsonl", linhas)
        with self.assertRaises(traco.ConteudoRecusado) as apanhado:
            traco.tracar([caminho])
        mensagem = str(apanhado.exception)
        self.assertEqual(traco.detectar(mensagem), [])
        self.assertIn("comprimento", mensagem)

    def test_um_carimbo_inteiro_e_recusado_porque_cabe_um_movel(self) -> None:
        """Nove dígitos são um carimbo Unix **e** um móvel angolano.

        Um campo de carimbo declarado `int` aceitava `912345678` com a forma
        certa, e nenhum detector de telefone o apanharia — já tinha passado a
        guarda como número. Daí a forma do carimbo ser só ISO-8601.
        """
        linhas = [{"tenant_id": TENANT, "ts": 912345678}]
        caminho = _escrever(self.raiz, "carimbo.jsonl", linhas)
        cadeias, descartes = traco.tracar([caminho])
        self.assertEqual([d.chave for d in descartes], ["ts"])
        self.assertEqual(len(cadeias), 1)

    def test_um_tipo_de_evento_com_maiusculas_e_descartado(self) -> None:
        linhas = [{"tenant_id": TENANT, "tipo": "Payment.Confirmed"}]
        caminho = _escrever(self.raiz, "tipo.jsonl", linhas)
        _, descartes = traco.tracar([caminho])
        self.assertEqual([d.chave for d in descartes], ["tipo"])

    def test_um_uuid_em_maiusculas_e_recusado(self) -> None:
        """Duas grafias do mesmo identificador fazem duas cadeias onde há uma."""
        linhas = [{"tenant_id": TENANT.upper()}]
        caminho = _escrever(self.raiz, "caixa.jsonl", linhas)
        with self.assertRaises(traco.ConteudoRecusado):
            traco.tracar([caminho])

    def test_uma_linha_que_nao_e_objecto_falha(self) -> None:
        caminho = self.raiz / "lista.jsonl"
        caminho.write_bytes(b'["isto", "e", "uma", "lista"]\n')
        with self.assertRaises(traco.ConteudoRecusado) as apanhado:
            traco.tracar([caminho])
        self.assertIn("é list", str(apanhado.exception))

    def test_uma_linha_que_nao_e_json_falha(self) -> None:
        caminho = self.raiz / "mau.jsonl"
        caminho.write_bytes(b"isto nao e json\n")
        with self.assertRaises(traco.ConteudoRecusado):
            traco.tracar([caminho])

    def test_linhas_em_branco_saltam_se(self) -> None:
        caminho = self.raiz / "brancos.jsonl"
        caminho.write_bytes(
            ("\n" + json.dumps({"tenant_id": TENANT}) + "\n\n").encode("utf-8")
        )
        cadeias, _ = traco.tracar([caminho])
        self.assertEqual(len(cadeias), 1)


class TestAGuardaFinalDaSaida(unittest.TestCase):
    """A terceira barreira existe porque as duas primeiras são código editável."""

    def _com_o_order_id_largo(self, valor: str):
        """Alarga a forma de uma chave que **chega à saída**, e devolve o traço.

        Tem de ser uma chave emitida pela `Cadeia`: a primeira versão deste
        ensaio alargou o `estado`, que o traço lê e **não emite**, pelo que o
        valor sujo nunca chegava à saída e o ensaio media a barreira errada —
        ficou verde pela razão errada e foi a mensagem de erro que o denunciou.
        """
        original = dict(traco.PERMITIDOS)
        larga = dict(original)
        larga["order_id"] = traco.Forma(
            "larga", lambda v: isinstance(v, str), "qualquer texto"
        )
        try:
            traco.PERMITIDOS = larga  # type: ignore[misc]
            with TemporaryDirectory() as pasta:
                caminho = _escrever(
                    Path(pasta), "largo.jsonl", [{"tenant_id": TENANT, "order_id": valor}]
                )
                cadeias, descartes = traco.tracar([caminho])
                with self.assertRaises(traco.ConteudoRecusado) as apanhado:
                    traco.como_json(cadeias, descartes)
                return str(apanhado.exception)
        finally:
            traco.PERMITIDOS = original  # type: ignore[misc]

    def test_um_valor_que_a_lista_deixasse_passar_e_apanhado_na_saida(self) -> None:
        """A mutação que mede a terceira barreira.

        Sem ela, alargar uma forma deixava o traço emitir um telefone com as
        duas primeiras guardas contentes.
        """
        self.assertIn("telefone_ao", self._com_o_order_id_largo(movel_de_forma_real()))

    def test_texto_livre_numa_chave_larga_e_apanhado_pelo_alfabeto(self) -> None:
        """O caso sem telefone: prosa num campo que devia ser identificador."""
        self.assertIn(
            "alfabeto estrutural", self._com_o_order_id_largo(conteudo_de_conversa())
        )

    def test_o_alfabeto_nao_dispara_na_prosa_deste_modulo(self) -> None:
        """A prosa do `em_falta` tem espaços e crases, e não é dado de entrada.

        Foi a primeira versão a correr o detector sobre o documento inteiro: ele
        disparava sempre, e **tapava** o achado que existe para dar.
        """
        with TemporaryDirectory() as pasta:
            caminho = _escrever(Path(pasta), "parcial.jsonl", cadeia_limpa()[:1])
            cadeias, descartes = traco.tracar([caminho])
            saida = json.loads(traco.como_json(cadeias, descartes))
        self.assertEqual(saida["resumo"]["completas"], 0)
        self.assertIn("consumo por `agr_servicos`", saida["cadeias"][0]["em_falta"])

    def test_a_saida_limpa_passa_as_tres_barreiras(self) -> None:
        """O par positivo: sem ele, uma guarda que recusasse tudo passava."""
        with TemporaryDirectory() as pasta:
            caminho = _escrever(Path(pasta), "limpo.jsonl", cadeia_limpa())
            cadeias, descartes = traco.tracar([caminho])
            saida = json.loads(traco.como_json(cadeias, descartes))
        self.assertEqual(saida["resumo"]["cadeias"], 1)
        self.assertEqual(saida["resumo"]["completas"], 1)
        self.assertEqual(saida["resumo"]["chaves_descartadas"], 0)


class TestOsElosEmFalta(unittest.TestCase):
    """Uma cadeia que para tem de dizer onde parou."""

    def setUp(self) -> None:
        self.pasta = TemporaryDirectory()
        self.raiz = Path(self.pasta.name)
        self.addCleanup(self.pasta.cleanup)

    def test_sem_consumo_a_cadeia_nomeia_o_elo(self) -> None:
        """É o estado do esqueleto hoje, e é o que o gate tem de ver.

        Sem a linha de `events_consumed` com `consumer = 'agr_servicos'`, a
        cadeia não está completa — e a diferença entre «não medido» e «medido e
        parou» é toda a diferença numa checklist.
        """
        linhas = cadeia_limpa()[:-1]
        caminho = _escrever(self.raiz, "parcial.jsonl", linhas)
        cadeias, _ = traco.tracar([caminho])
        self.assertEqual(cadeias[0].em_falta, ("consumo por `agr_servicos`",))
        self.assertFalse(cadeias[0].completa())

    def test_um_consumo_de_outra_vertical_nao_fecha_o_elo(self) -> None:
        """O critério é «consumido pela vertical **Serviços**», não «consumido»."""
        linhas = cadeia_limpa()
        linhas[-1]["consumer"] = "agr_vendedor"
        caminho = _escrever(self.raiz, "outra.jsonl", linhas)
        cadeias, _ = traco.tracar([caminho])
        self.assertEqual(cadeias[0].em_falta, ("consumo por `agr_servicos`",))
        self.assertEqual(cadeias[0].consumidores, ("agr_vendedor",))

    def test_um_consumo_de_outro_evento_nao_fecha_o_elo(self) -> None:
        """A linha certa sobre o evento errado não é o consumo deste evento."""
        linhas = cadeia_limpa()
        linhas[-1]["event_id"] = "99999999-8888-4777-8666-555555555555"
        caminho = _escrever(self.raiz, "troca.jsonl", linhas)
        cadeias, _ = traco.tracar([caminho])
        self.assertEqual(cadeias[0].em_falta, ("consumo por `agr_servicos`",))

    def test_sem_pedido_nem_evento_a_cadeia_nomeia_os_tres(self) -> None:
        linhas = [cadeia_limpa()[0]]
        caminho = _escrever(self.raiz, "so-mensagem.jsonl", linhas)
        cadeias, _ = traco.tracar([caminho])
        self.assertEqual(
            cadeias[0].em_falta,
            ("pedido", "evento de pagamento", "consumo por `agr_servicos`"),
        )

    def test_um_order_id_explicito_tambem_fecha_o_elo_do_pedido(self) -> None:
        """As consultas dão `entity_id`; um *log* futuro pode dar `order_id`."""
        linhas = [{"tenant_id": TENANT, "order_id": PEDIDO}]
        caminho = _escrever(self.raiz, "ordem.jsonl", linhas)
        cadeias, _ = traco.tracar([caminho])
        self.assertEqual(cadeias[0].order_id, PEDIDO)

    def test_uma_entidade_que_nao_e_pedido_nao_fecha_o_elo(self) -> None:
        linhas = [{"tenant_id": TENANT, "entity": "contacto", "entity_id": PEDIDO}]
        caminho = _escrever(self.raiz, "outra-entidade.jsonl", linhas)
        cadeias, _ = traco.tracar([caminho])
        self.assertIsNone(cadeias[0].order_id)
        self.assertIn("pedido", cadeias[0].em_falta)

    def test_a_marcacao_aparece_quando_existe_e_nao_e_elo(self) -> None:
        """O efeito do P7 conta-se à parte: é o que o G0-1 pede depois da cadeia."""
        linhas = cadeia_limpa() + [{"tenant_id": TENANT, "booking_id": MARCACAO}]
        caminho = _escrever(self.raiz, "com-marcacao.jsonl", linhas)
        cadeias, _ = traco.tracar([caminho])
        self.assertEqual(cadeias[0].booking_id, MARCACAO)
        self.assertTrue(cadeias[0].completa())

    def test_dois_tenants_dao_duas_cadeias(self) -> None:
        outro = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        linhas = cadeia_limpa() + [{"tenant_id": outro, "msg_id": MENSAGEM}]
        caminho = _escrever(self.raiz, "dois.jsonl", linhas)
        cadeias, _ = traco.tracar([caminho])
        self.assertEqual([c.tenant_id for c in cadeias], sorted([TENANT, outro]))

    def test_uma_linha_sem_tenant_nao_entra_em_cadeia_nenhuma(self) -> None:
        """Sem `tenant_id` não há a que *tenant* a linha pertence, e inventar era pior."""
        linhas = [{"consumer": "agr_servicos"}]
        caminho = _escrever(self.raiz, "sem-tenant.jsonl", linhas)
        cadeias, _ = traco.tracar([caminho])
        self.assertEqual(cadeias, [])

    def test_varias_entradas_juntam_se_numa_cadeia(self) -> None:
        """O caso real: os *logs* num ficheiro e as consultas noutro."""
        linhas = cadeia_limpa()
        um = _escrever(self.raiz, "logs.jsonl", linhas[:1])
        dois = _escrever(self.raiz, "base.jsonl", linhas[1:])
        cadeias, _ = traco.tracar([um, dois])
        self.assertEqual(len(cadeias), 1)
        self.assertTrue(cadeias[0].completa())

    def test_sem_entradas_levanta_elo_em_falta(self) -> None:
        with self.assertRaises(traco.EloEmFalta):
            traco.tracar([])


class TestOTipoDeEventoAceito(unittest.TestCase):
    """Só os dois tipos que o critério G0-1 nomeia fecham o elo do evento."""

    def setUp(self) -> None:
        self.pasta = TemporaryDirectory()
        self.raiz = Path(self.pasta.name)
        self.addCleanup(self.pasta.cleanup)

    def test_o_payment_confirmed_fecha_o_elo(self) -> None:
        linhas = cadeia_limpa()
        linhas[2]["tipo"] = "payment.confirmed"
        caminho = _escrever(self.raiz, "sandbox.jsonl", linhas)
        cadeias, _ = traco.tracar([caminho])
        self.assertEqual(cadeias[0].tipo_do_evento, "payment.confirmed")
        self.assertTrue(cadeias[0].completa())

    def test_o_reference_issued_nao_fecha_o_elo(self) -> None:
        """A referência é o P3; o evento que o gate pede é a **confirmação**."""
        linhas = cadeia_limpa()
        linhas[2]["tipo"] = "payment.reference_issued"
        caminho = _escrever(self.raiz, "referencia.jsonl", linhas)
        cadeias, _ = traco.tracar([caminho])
        self.assertIsNone(cadeias[0].event_id)
        self.assertIn("evento de pagamento", cadeias[0].em_falta)


if __name__ == "__main__":
    unittest.main()
