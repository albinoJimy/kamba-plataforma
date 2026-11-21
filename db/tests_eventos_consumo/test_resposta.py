"""A resposta do AGR pela fila: turno -> evento -> BullMQ -> Saida (KAM-227, criterio 4).

O criterio 4 do KAM-224 provou-se contra a base e o `GraphFalso`, mas **nao
pela fila**: o consumo corria pelo `processar` do KAM-006 e nao por um *worker*
BullMQ. Esta suite e essa metade, com a base e a fila reais da `ComConsumidor`:

* o turno grava a resposta e emite o `agent.replied` com as instrucoes do
  proprio `services/agr/src/kamba_agr/saida.py` (lidas do ficheiro pelo `ast`,
  nao copiadas: uma copia era uma segunda fonte que podia divergir);
* o publicador do KAM-005 leva o evento as filas `evt.outbound.p<n>`;
* o `tests_bd/resposta_runner.ts` consome-o com o `efeitoDoOutbound` e o
  `envioPeloSaida` de producao, e conta cada chamada a Meta numa linha `envio`.

O cliente da Meta e o destinatario do *runner* sao duplos: as duas portas de
producao provam-se contra a base em `tests_bd/resposta.bd.test.ts`.
"""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path

from tests.factories import canal as criar_canal
from tests.factories import contacto as criar_contacto
from tests.factories import contexto
from tests.factories import tenant as criar_tenant
from tests_eventos import node

from tests_eventos_consumo.base import ESCADA_ACELERADA, ESPERA, ESPERA_DA_DLQ, ComConsumidor, esperar_por

CONSUMIDOR = "outbound"
TIPO = "agent.replied"
SAIDA_DO_AGR = Path(__file__).resolve().parents[2] / "services" / "agr" / "src" / "kamba_agr" / "saida.py"


def _sql_do_agr(nome: str) -> str:
    """Uma constante de SQL do `saida.py`, lida pelo `ast` e sem importar o AGR."""
    arvore = ast.parse(SAIDA_DO_AGR.read_text(encoding="utf-8"))
    for no in arvore.body:
        alvo = no.target if isinstance(no, ast.AnnAssign) else (no.targets[0] if isinstance(no, ast.Assign) else None)
        if isinstance(alvo, ast.Name) and alvo.id == nome and no.value is not None:
            return ast.literal_eval(no.value)
    raise AssertionError(f"o saida.py nao tem {nome}")


SQL_INSERIR = _sql_do_agr("SQL_INSERIR")
SQL_EMITIR = _sql_do_agr("SQL_EMITIR")


class ComResposta(ComConsumidor):
    """A `ComConsumidor`, com conversas reais e o consumidor `outbound`."""

    def setUp(self) -> None:
        super().setUp()
        self._tenants: list[str] = []
        self.addCleanup(self._limpar_respostas)
        # Os processos morrem antes de se apagar o que eles escrevem: o
        # `addCleanup` corre pela ordem inversa (a nota da `ComConsumidor`).
        self.addCleanup(self._parar_processos)
        # A `ComFila` apaga todas as subscricoes entre testes; a da `0073`
        # semeia-se aqui, com os valores do `registry/outbound.yaml`.
        self.subscrever(CONSUMIDOR, TIPO, finalidade="atendimento", versao_max=2, exige_ordem=False)

    def _limpar_respostas(self) -> None:
        for tenant in self._tenants:
            for tabela in (
                "outbound_messages",
                "agent_replies",
                "events_consumed",
                "events_dlq",
                "conversations",
                "contacts",
                "tenant_channels",
            ):
                self.cursor.execute(f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (tenant,))
            self.cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (tenant,))

    def conversa(self) -> dict[str, str]:
        """Um tenant, um canal, um contacto e uma conversa com a janela aberta."""
        tenant = criar_tenant(self.cursor)
        self._tenants.append(tenant)
        canal = criar_canal(self.cursor, tenant)
        contacto = criar_contacto(self.cursor, tenant)
        conversa = str(uuid.uuid4())
        self.cursor.execute(
            "INSERT INTO platform.conversations "
            "(id, tenant_id, contact_id, channel_id, mode, last_inbound_at, window_expires_at) "
            "VALUES (%s, %s, %s, %s, 'bot', now(), now() + interval '24 hours')",
            (conversa, tenant, contacto, canal),
        )
        contexto(self.cursor, None)
        self.cursor.execute(
            "SELECT phone_number_id FROM platform.tenant_channels WHERE id = %s", (canal,)
        )
        numero = str(self.cursor.fetchone()[0])
        return {"tenant": tenant, "contacto": contacto, "canal": canal, "conversa": conversa, "numero": numero}

    def turno(self, c: dict[str, str], chave: str) -> str:
        """O que o `enfileirar` do AGR faz: a linha e o evento. Devolve o `event_id`."""
        self.cursor.execute(
            SQL_INSERIR,
            (c["tenant"], chave, c["contacto"], c["conversa"], "whatsapp", "Temos em stock.", "[]",
             "2026-11-19T11:59:58Z"),
        )
        reply_id = str(self.cursor.fetchone()[0])
        payload = {
            "reply_id": reply_id,
            "thread_id": f"{c['tenant']}:{c['contacto']}",
            "conversation_id": c["conversa"],
            "contact_id": c["contacto"],
            "canal": "whatsapp",
        }
        return self._emitir(c["tenant"], c["conversa"], payload)

    def _emitir(self, tenant: str, conversa: str, payload: dict) -> str:
        self.cursor.execute(SQL_EMITIR, (TIPO, tenant, conversa, json.dumps(payload, sort_keys=True)))
        return str(self.cursor.fetchone()[0])

    def entregue(self, c: dict[str, str]) -> bool:
        self.cursor.execute(
            "SELECT bool_and(entregue_at IS NOT NULL) FROM platform.agent_replies WHERE tenant_id = %s",
            (c["tenant"],),
        )
        return bool(self.cursor.fetchone()[0])

    def publicar_pendentes(self, rotulo: str) -> None:
        publicador = self.lancar_publicador(rotulo)
        self.assertTrue(
            esperar_por(lambda: self.pendentes() == 0, ESPERA),
            f"o publicador nao publicou{self.diagnostico()}",
        )
        publicador.parar()

    def lancar_resposta(self) -> node.Processo:
        processo = node.lancar(
            ["tests_bd/resposta_runner.ts"],
            {
                "KAMBA_CONSUMIDOR_DB_URL": node.url_da_base(na_rede=self._na_rede(), papel="app"),
                "KAMBA_CON_ESCADA": ",".join(str(ms) for ms in ESCADA_ACELERADA),
            },
            rotulo="resposta",
            registo=self.registos / "resposta.log",
            variavel_do_registo="KAMBA_CON_REGISTO",
        )
        self.processos.append(processo)
        self.assertTrue(self.esperar_arranque(processo), self.diagnostico())
        return processo

    @staticmethod
    def envios(processo: node.Processo) -> list[dict]:
        """Uma linha por chamada a Meta, com o tenant e o numero do canal do pedido."""
        return [linha for linha in processo.linhas() if linha.get("evento") == "envio"]

    @staticmethod
    def respostas(processo: node.Processo) -> list[str]:
        return [str(linha.get("desfecho")) for linha in processo.linhas() if linha.get("evento") == "resposta"]


class TestUmTurnoUmEnvioPelaFila(ComResposta):
    def test_um_turno_da_um_envio_e_a_reentrega_tres_vezes_pelo_bullmq_continua_a_dar_um(self) -> None:
        c = self.conversa()
        evento = self.turno(c, "wamid.fila:0")
        self.publicar_pendentes("p")
        processo = self.lancar_resposta()
        self.assertTrue(
            esperar_por(lambda: self.consumidos(CONSUMIDOR) == 1, ESPERA),
            f"o evento nao foi consumido{self.diagnostico()}",
        )
        self.assertEqual(self.respostas(processo), ["enviada"])
        self.assertTrue(self.entregue(c))

        # A reentrega pelo caminho real, tres vezes: a fila esquece o *job* e o
        # outbox volta a ter a linha por publicar (a nota do `esquecer_na_fila`).
        for vez in range(1, 4):
            self.esquecer_na_fila(evento, CONSUMIDOR)
            self.republicar(evento)
            self.publicar_pendentes(f"p{vez}")
            self.assertTrue(
                esperar_por(lambda vez=vez: len(self.desfechos(processo, evento)) == 1 + vez, ESPERA),
                f"a reentrega {vez} nao chegou ao consumidor{self.diagnostico()}",
            )

        self.assertEqual(self.desfechos(processo, evento), ["aplicado", "duplicado", "duplicado", "duplicado"])
        self.assertEqual(len(self.envios(processo)), 1, "uma chamada a Meta")
        self.assertEqual(self.consumidos(CONSUMIDOR), 1)
        self.cursor.execute(
            "SELECT idempotency_key, state FROM platform.outbound_messages WHERE tenant_id = %s",
            (c["tenant"],),
        )
        self.assertEqual([tuple(l) for l in self.cursor.fetchall()], [("wamid.fila:0", "sent")])


class TestIsolamentoPelaFila(ComResposta):
    def test_um_evento_de_outro_tenant_nao_chega_ao_consumidor_errado(self) -> None:
        a = self.conversa()
        b = self.conversa()
        self.turno(a, "wamid.a:0")
        self.turno(b, "wamid.b:0")
        # O `reply_id` de A num evento emitido por B: o envelope e de B, e sob a
        # RLS de B a linha de A nao existe.
        self.cursor.execute("SELECT reply_id::text FROM platform.agent_replies WHERE tenant_id = %s", (a["tenant"],))
        reply_de_a = self.cursor.fetchone()[0]
        forjado = self._emitir(
            b["tenant"],
            b["conversa"],
            {
                "reply_id": reply_de_a,
                "thread_id": f"{b['tenant']}:{a['contacto']}",
                "conversation_id": a["conversa"],
                "contact_id": a["contacto"],
                "canal": "whatsapp",
            },
        )
        self.publicar_pendentes("p")
        processo = self.lancar_resposta()
        self.assertTrue(
            esperar_por(
                lambda: len(self.envios(processo)) == 2 and len(self.na_dlq(CONSUMIDOR)) == 1, ESPERA_DA_DLQ
            ),
            f"os tres eventos nao acabaram{self.diagnostico()}",
        )
        envios = self.envios(processo)
        # Um envio por tenant, cada um com o tenant **e** o numero do seu canal.
        self.assertEqual(
            sorted((e["tenant_id"], e["phone_number_id"]) for e in envios),
            sorted([(a["tenant"], a["numero"]), (b["tenant"], b["numero"])]),
        )
        (dlq,) = self.na_dlq(CONSUMIDOR)
        self.assertEqual(dlq["event_id"], forjado)
        self.assertEqual(dlq["envelope"]["tenant_id"] if isinstance(dlq["envelope"], dict)
                         else json.loads(dlq["envelope"])["tenant_id"], b["tenant"])
        self.assertIn("RespostaInexistente", dlq["erro"])
        self.cursor.execute(
            "SELECT tenant_id::text, idempotency_key FROM platform.outbound_messages "
            "WHERE tenant_id = ANY(%s::uuid[]) ORDER BY 2",
            ([a["tenant"], b["tenant"]],),
        )
        self.assertEqual(
            sorted(tuple(l) for l in self.cursor.fetchall()),
            sorted([(a["tenant"], "wamid.a:0"), (b["tenant"], "wamid.b:0")]),
        )
        self.assertTrue(self.entregue(a))
        self.assertTrue(self.entregue(b))
