"""O `ConversaState` base nasce do contexto e de mais nada (`docs/tecnica/02` §5.3)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from apoio import invocacao_crua
from kamba_agr.contexto import ler_invocacao
from kamba_agr.estado import (
    ESTAGIO_INICIAL,
    ESTAGIOS,
    SCHEMA_VERSION,
    ConversaState,
    TIPOS_DE_ENTRADA,
    VersaoDeEstadoAFrenteError,
    estado_inicial,
    tipo_de_entrada,
    recortar_janela,
    versao_lida,
)

#: As chaves do bloco de codigo do §5.3, tal como la estao escritas. Eram
#: vinte e tres; a emenda 1.40 (KAM-031) acrescenta `ofertas`, `avisos` e
#: `handoff_motivo`, e o `admissao`, e eram **vinte e seis**. O comentario dizia
#: «dezenove» e nunca foram dezenove — a lista abaixo e a prova, e e ela que o
#: teste compara.
#:
#: A emenda 1.44 (KAM-114) acrescenta **uma** chave a esta lista, o `concierge`,
#: e sao **vinte e sete**.
#:
#: **O `turn_seq` nao entra aqui de proposito, e a assimetria e o remedio de um
#: defeito medido.** O `turno.py` passa o `estado_inicial` ao `ainvoke` em
#: **cada** turno, pelo que toda a chave desta lista sobrescreve a do
#: *checkpoint*. Com o `turn_seq` ca, ele valia 1 em todos os turnos e o
#: `draft_id = sha256(thread_id:turn_seq)` era o mesmo em toda a conversa: o
#: rascunho do 2.o turno era engolido pelo `ON CONFLICT` e a conversa ficava
#: **muda**. Ele vive so no `ConversaState` (que e `total=False`) e no
#: *checkpoint*.
#:
#: O `concierge` fica, e o reinicio por turno e a propriedade que impede a
#: decisao de um turno de valer como aprovacao no turno seguinte.
CHAVES_DO_521 = (
    "schema_version",
    "tenant_id",
    "channel_id",
    "contact_id",
    "conversation_id",
    "vertical",
    "turn_id",
    "thread_id",
    "input_kind",
    "messages",
    "summary",
    "stt",
    "guard",
    "intent",
    "admissao",
    "facts",
    "ofertas",
    "avisos",
    "handoff_motivo",
    "cart",
    # **O `stage` NAO esta aqui, e e a outra metade da correccao do KAM-035.**
    # Ele continua a ser chave do `ConversaState` — o que saiu foi a
    # inicializacao por turno, porque o botao de confirmacao chega **sempre** no
    # turno seguinte e o `awaiting_confirm` escrito pelo turno anterior era
    # apagado a entrada. **Toda** a confirmacao saia `STALE_CONFIRMATION`, nas
    # duas verticais. Quem o estabelece agora e o `ingest`, quando o valor nao
    # esta nos `ESTAGIOS`; medido pela revisao adversarial (`ANALISE-40`,
    # achado 3).
    # **O `slots` NAO esta aqui, e e a correccao do KAM-035.** Ele continua a ser
    # chave do `ConversaState` (§5.3 da-lha, e o `test_as_chaves_do_estado`
    # mede-o) — o que saiu foi a **inicializacao por turno**.
    #
    # O `turno.py` chama `estado_inicial` em cada turno e passa o resultado ao
    # `ainvoke`, pelo que toda a chave que nasca aqui sobrescreve a do
    # *checkpoint*. Com `slots: None` nesta tabela, o §8.2 — «slots preenchidos
    # ao longo de varios turnos» — era impossivel: o servico que o cliente deu
    # no turno 1 desaparecia no turno 2 e o `slots_collect` repetia a mesma
    # pergunta para sempre. **Medido** com um `MemorySaver` e dois turnos, e e a
    # mesma medicao que o KAM-114 fez para o `turn_seq`.
    "draft",
    "citation_retries",
    "handoff_seq",
    "handoff",
    # KAM-114, emenda 1.44. **Nao esta no bloco do §5.3**, que este ticket nao
    # altera: vem do bloco do KAM-114 e do dicionario §3.34. O
    # `test_as_chaves_sao_as_que_o_documento_escreve` continua a passar porque e
    # de inclusao num sentido — o documento e subconjunto desta lista.
    "concierge",
    # KAM-037, emenda 1.46. Pela mesma razao do `concierge`: **nao esta no bloco
    # do §5.3**, que este ticket tambem nao altera — vem do bloco do KAM-037 e
    # do dicionario §3.35.
    "degradado",
)


class TestEstadoInicial(unittest.TestCase):
    def test_as_chaves_sao_as_do_521_e_nenhuma_e_nova(self) -> None:
        # §3 do dicionario: um nome novo entra no dicionario antes de entrar em
        # codigo. Este teste e o que impede uma chave inventada de passar.
        estado = estado_inicial(ler_invocacao(invocacao_crua()))
        self.assertEqual(sorted(estado), sorted(CHAVES_DO_521))

    def test_tres_chaves_do_estado_nao_nascem_no_estado_inicial(self) -> None:
        """E o que as deixa atravessar turnos. Ver as notas no `estado.py`.

        O `turn_seq` (KAM-114), o `slots` e o `stage` (KAM-035) sao chaves do
        `ConversaState` e **nao** da tabela do `estado_inicial`: esta funcao
        corre em cada turno e o que ela devolve sobrescreve o *checkpoint*.
        """
        estado = estado_inicial(ler_invocacao(invocacao_crua()))
        fora = {"turn_seq", "slots", "stage"}
        for chave in fora:
            self.assertNotIn(chave, estado, chave)
            self.assertIn(chave, ConversaState.__annotations__, chave)
        # E o resto do `ConversaState` **esta** todo: a ausencia e das tres e de
        # mais nenhuma.
        self.assertEqual(
            set(ConversaState.__annotations__) - set(estado), fora
        )

    def test_as_chaves_sao_as_que_o_documento_escreve(self) -> None:
        # Nao de memoria: le-se o §5.3 do documento e confrontam-se os nomes.
        doc = (
            Path(__file__).resolve().parents[3]
            / "docs"
            / "tecnica"
            / "02_Agent_Runtime_Verticais.md"
        ).read_text(encoding="utf-8")
        bloco = doc.split("### 5.3 Estado partilhado")[1].split("```")[1]
        declaradas = set(re.findall(r"^\s{4}(\w+):", bloco, re.MULTILINE))
        # O bloco do documento escreve tres pares na mesma linha
        # (`channel_id: str; contact_id: str; conversation_id: str`), que a
        # expressao acima nao apanha — por isso o teste e de inclusao num
        # sentido e a igualdade exacta fica no teste de cima.
        self.assertTrue(declaradas)
        # **Confronta-se com o `ConversaState` e nao com o `CHAVES_DO_521`.** O
        # documento descreve o **estado**, e tres das chaves dele nao nascem no
        # `estado_inicial` de proposito (ver o ensaio acima) — comparar com a
        # tabela da inicializacao punha o documento a parecer errado por causa
        # de uma decisao do codigo.
        self.assertTrue(
            declaradas.issubset(set(ConversaState.__annotations__)), declaradas
        )

    def test_os_identificadores_vem_todos_da_invocacao(self) -> None:
        invocacao = ler_invocacao(invocacao_crua())
        estado = estado_inicial(invocacao)
        self.assertEqual(estado["tenant_id"], invocacao.tenant_id)
        self.assertEqual(estado["channel_id"], invocacao.channel_id)
        self.assertEqual(estado["contact_id"], invocacao.contact_id)
        self.assertEqual(estado["conversation_id"], invocacao.conversation_id)
        self.assertEqual(estado["vertical"], invocacao.vertical)
        self.assertEqual(estado["turn_id"], invocacao.wamid)
        self.assertEqual(estado["thread_id"], invocacao.thread_id)

    def test_nasce_com_a_versao_deste_codigo_e_sem_estagio(self) -> None:
        """O `stage` nao nasce aqui — nasce no `ingest`. Ver o `estado.py`."""
        estado = estado_inicial(ler_invocacao(invocacao_crua()))
        self.assertEqual(estado["schema_version"], SCHEMA_VERSION)
        self.assertNotIn("stage", estado)
        # E o valor que o `ingest` estabelece continua a ser um dos conhecidos.
        self.assertIn(ESTAGIO_INICIAL, ESTAGIOS)

    def test_os_facts_nascem_vazios_em_cada_turno(self) -> None:
        # §5.3: «so deste turno; reiniciado em `ingest`». Um *fact* de um turno
        # anterior e um numero sem prova neste.
        invocacao = ler_invocacao(invocacao_crua())
        primeiro = estado_inicial(invocacao)
        primeiro["facts"].append({"inventado": 1})
        self.assertEqual(estado_inicial(invocacao)["facts"], [])

    def test_o_input_kind_cai_nos_cinco_valores(self) -> None:
        for wa_type in ("text", "audio", "image", "location", "interactive"):
            with self.subTest(wa_type=wa_type):
                self.assertEqual(tipo_de_entrada(wa_type), wa_type)
        for wa_type in ("button", "sticker", "document", "order", "system"):
            with self.subTest(wa_type=wa_type):
                self.assertIn(tipo_de_entrada(wa_type), TIPOS_DE_ENTRADA)


class TestVersaoDeEstado(unittest.TestCase):
    def test_um_estado_sem_a_chave_conta_como_um(self) -> None:
        self.assertEqual(versao_lida({}), 1)

    def test_a_versao_deste_codigo_le_se(self) -> None:
        self.assertEqual(versao_lida({"schema_version": SCHEMA_VERSION}), SCHEMA_VERSION)

    def test_uma_versao_a_frente_levanta_em_vez_de_degradar(self) -> None:
        # Correr um turno sobre um estado da versao N+1 reescreve-o **sem** as
        # chaves que este codigo nao conhece: e perder dados de uma conversa.
        with self.assertRaises(VersaoDeEstadoAFrenteError):
            versao_lida({"schema_version": SCHEMA_VERSION + 1})

    def test_uma_versao_que_nao_e_inteiro_levanta(self) -> None:
        for valor in ("1", 1.5, None, True, 0, -1, [1]):
            with self.subTest(valor=valor), self.assertRaises(
                VersaoDeEstadoAFrenteError
            ):
                versao_lida({"schema_version": valor})


class TestRecorteDaJanela(unittest.TestCase):
    """O «estado minimo» do §12: ultimas K mensagens mais o `summary`."""

    def test_abaixo_do_maximo_devolve_o_mesmo_estado(self) -> None:
        estado = {"messages": [1, 2, 3], "summary": None}
        self.assertIs(recortar_janela(estado, 20), estado)

    def test_no_maximo_exacto_nao_corta(self) -> None:
        # A fronteira **pelo valor**: com `<` em vez de `<=` perdia-se a
        # mensagem mais antiga de uma janela que ja cabia.
        estado = {"messages": list(range(20))}
        self.assertEqual(recortar_janela(estado, 20)["messages"], list(range(20)))

    def test_acima_do_maximo_deixa_as_ultimas(self) -> None:
        # As ultimas e nao as primeiras: o principio de uma conversa e o que o
        # `summary` ja resume.
        recortado = recortar_janela({"messages": list(range(25))}, 20)
        self.assertEqual(recortado["messages"], list(range(5, 25)))

    def test_uma_janela_de_zero_esvazia(self) -> None:
        # O caso que um `[-maximo:]` ingenuo erra: `[-0:]` e a lista inteira.
        self.assertEqual(recortar_janela({"messages": [1, 2]}, 0)["messages"], [])

    def test_nao_muta_o_estado_que_recebe(self) -> None:
        estado = {"messages": list(range(25)), "stage": "browsing"}
        recortar_janela(estado, 5)
        self.assertEqual(len(estado["messages"]), 25)

    def test_as_outras_chaves_passam_intactas(self) -> None:
        estado = {"messages": list(range(25)), "stage": "cart", "summary": "x"}
        recortado = recortar_janela(estado, 2)
        self.assertEqual(recortado["stage"], "cart")
        self.assertEqual(recortado["summary"], "x")

    def test_sem_mensagens_devolve_o_mesmo(self) -> None:
        for estado in ({"messages": None}, {}, {"messages": []}):
            with self.subTest(estado=estado):
                self.assertIs(recortar_janela(estado, 20), estado)

    def test_uma_janela_negativa_levanta(self) -> None:
        with self.assertRaises(ValueError):
            recortar_janela({"messages": [1]}, -1)


if __name__ == "__main__":
    unittest.main()
