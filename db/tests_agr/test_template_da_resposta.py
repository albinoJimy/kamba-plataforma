"""O template da resposta do AGR contra o PostgreSQL (KAM-221, revisao `0076`).

O que os duplos de `services/agr/tests/test_pela_resposta.py` nao provam, e so
a base diz:

| Propriedade | Porque precisa da base |
|---|---|
| a resposta de *template* grava o nome e os **valores**, e emite um evento | o `SQL_INSERIR_COM_TEMPLATE` e a `evt_emitir`, na mesma transaccao |
| parametros sem *template*, um nome fora da forma da Meta e um parametro nulo recusam | as tres restricoes da revisao |
| o `kamba_app` nao muda o *template* de uma resposta ja emitida | o `UPDATE` por coluna, so o `entregue_at` |
| a resposta de texto livre de um turno continua sem *template* | o `SQL_INSERIR` do KAM-224, intacto |

As instrucoes sao as de `kamba_agr.saida`, chamadas pela funcao do modulo.
"""

from __future__ import annotations

import tests_agr.test_agent_replies as resposta_do_agr
from tests.base import PRIVILEGIO_INSUFICIENTE, VIOLACAO_DE_CHECK, sqlstate

# O `tests_agr.base` poe o `services/agr/src` no caminho, e por isso vem antes.
from kamba_agr import saida  # noqa: E402
from kamba_core import tenant_guard  # noqa: E402

REFERENCIA = "ORC-ABCDEFGH"


class TestTemplateDaResposta(resposta_do_agr.ComSaida):
    def _template(self) -> list[tuple]:
        self.semente.execute(
            "SELECT chave, template_nome, template_parametros FROM platform.agent_replies "
            "WHERE tenant_id = %s ORDER BY criado_at",
            (self.tenant,),
        )
        return [(c, n, list(p)) for (c, n, p) in self.semente.fetchall()]

    def test_a_resposta_de_template_grava_o_nome_e_os_valores_e_emite_uma_vez(self) -> None:
        primeira = self.emitir(chave="orcamento:q:1", template="orcamento_pronto", parametros=(REFERENCIA,))
        repetida = self.emitir(chave="orcamento:q:1", template="orcamento_pronto", parametros=(REFERENCIA,))
        self.assertIsNotNone(primeira)
        self.assertIsNone(repetida)
        self.assertEqual(self._template(), [("orcamento:q:1", "orcamento_pronto", [REFERENCIA])])
        self.assertEqual(len(self._eventos()), 1)
        # O evento continua sem conteudo: nem o texto nem os parametros.
        self.assertNotIn(REFERENCIA, str(self._eventos()[0]))

    def test_a_resposta_de_texto_livre_continua_sem_template(self) -> None:
        self.emitir()
        self.assertEqual(self._template(), [("wamid.ensaio:0", None, [])])

    def _inserir(self, nome, parametros) -> None:
        c = self.conversa
        with tenant_guard.tx(self.app, self.tenant) as cursor:
            cursor.execute(
                saida.SQL_INSERIR_COM_TEMPLATE,
                (self.tenant, "k:recusa", c.contact_id, c.conversation_id, "whatsapp",
                 "ola", "[]", None, nome, parametros),
            )

    def test_as_tres_restricoes_recusam(self) -> None:
        for nome, parametros in (
            (None, [REFERENCIA]),              # parametros sem template
            ("Orcamento-Pronto", []),          # fora da forma da Meta
            ("orcamento_pronto", [None]),      # um parametro nulo
        ):
            with self.subTest(nome=nome, parametros=parametros):
                with self.assertRaises(Exception) as erro:
                    self._inserir(nome, parametros)
                self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_CHECK)
        self.assertEqual(self._template(), [])

    def test_o_kamba_app_nao_muda_o_template_de_uma_resposta_emitida(self) -> None:
        self.emitir(chave="orcamento:q:1", template="orcamento_pronto", parametros=(REFERENCIA,))
        for coluna, valor in (("template_nome", "outro"), ("template_parametros", "{X}")):
            with self.subTest(coluna=coluna):
                with self.assertRaises(Exception) as erro:
                    with tenant_guard.tx(self.app, self.tenant) as cursor:
                        cursor.execute(
                            f"UPDATE platform.agent_replies SET {coluna} = %s WHERE tenant_id = %s",
                            (valor, self.tenant),
                        )
                self.assertEqual(sqlstate(erro.exception), PRIVILEGIO_INSUFICIENTE)
        self.assertEqual(self._template(), [("orcamento:q:1", "orcamento_pronto", [REFERENCIA])])
