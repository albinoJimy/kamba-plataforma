"""Criterios 3, 4, 5 e 8 do KAM-046: a idempotencia da criacao, contra PostgreSQL.

O que **so aqui** se prova, e nenhum duplo de teste pode: que cinquenta sagas
concorrentes com a mesma `intent_key` deixam **uma** encomenda, **um**
`order.created` no outbox e cinquenta respostas iguais. Um `Promise.all` sobre um
objecto em memoria nao tem transaccoes para serializar e prova zero — e a licao
nao e teorica: a caixa de concorrencia do KAM-043 ficou **NAO VERIFICADO**
exactamente por isso, e esta escrito no bloco dele.

## O que esta suite replica, e o que ela nao e

Replica o **protocolo** da saga do §6.3 em Python, com as cadeias SQL lidas de
`services/com/src/orders/consultas.ts` — como o `test_concorrencia.py` do KAM-044
faz para o CAS da `transition`. Nao e a funcao `createOrder` do TypeScript a
correr: e o mesmo protocolo contra o mesmo motor, com o mesmo texto SQL.

A divisao do trabalho entre as duas suites e deliberada, e cada metade cobre o
que a outra nao consegue:

```text
services/com/tests/orders.intents.test.ts   a chave nao tem tempo nem telefone
                                            duas ordens das mesmas linhas, um hash
db/tests_encomendas/test_idempotencia.py     a mesma chave, cinquenta ligacoes, uma encomenda
```

**A fronteira da janela das 14:04:59/14:05:01 mede-se nas duas pontas**, e e a
unica forma de a medir: que a chave e a **mesma** nos dois instantes e uma
propriedade da derivacao e mede-se em TypeScript; que a mesma chave da **uma**
encomenda e uma propriedade das transaccoes e mede-se aqui. Nenhuma das duas
sozinha fecha o criterio.

## O `INSERT` do recibo escreve-se aqui, e porque

O modulo insere por `repo.inserirNoTenant`, que **constroi** o `INSERT` com a
coluna do filtro — nao ha constante para ler. O `consultas.py` ja escreve esta
limitacao para os tres `INSERT` do KAM-044, e vale igual para este: o texto do
`INSERT` do modulo nao e exercitado aqui, e e exercitado pela suite do proprio
repo-base, que e quem o constroi. O que esta suite escreve e o **sufixo**, que e
a parte que vem do modulo (`ON CONFLICT (tenant_id, intent_key) DO NOTHING`) e a
que serializa as cinquenta.

## Sao cinquenta ligacoes e nao cinquenta cursores

Na mesma ligacao, a segunda instrucao ve a primeira: o `ON CONFLICT DO NOTHING`
saltava por conflito com uma linha da propria transaccao e nada se media. Uma
ligacao por saga e a unica forma de as ter a disputar a mesma chave — a mesma
razao que o `test_concorrencia.py` escreve para as vinte transicoes.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import json
import uuid

import ligacao
import pg8000.dbapi
from tests.base import sqlstate
from tests_encomendas.base import LINHAS, TOTAL, ComEncomendas
from tests_encomendas.consultas import (
    SQL_CONCLUIR_INTENCAO,
    SQL_ENCOMENDA_DA_CHAVE,
    SQL_CONFIRMACAO_DO_DONO,
    SQL_EMITIR,
    SQL_FALHAR_INTENCAO,
    SQL_LER_CONFIRMACAO,
    SQL_LER_INTENCAO,
    SQL_PEDIDO_POR_PAGAR,
    SQL_RETOMAR_INTENCAO,
)

#: Cinquenta, como o criterio 3 pede.
SAGAS = 50

#: Os dois minutos do `MINUTOS_PARA_RETOMAR` (dicionario §3.28, §6.3 ponto 4).
MINUTOS_PARA_RETOMAR = 2

#: Os trinta minutos da janela do «ja tem o pedido por pagar» (criterio 8).
MINUTOS_DO_PEDIDO_POR_PAGAR = 30

#: O `INSERT` do recibo com o sufixo do modulo. Ver a nota do modulo.
SQL_RESERVAR_INTENCAO = """
  INSERT INTO platform.order_intents (tenant_id, intent_key, draft_hash)
  VALUES (%s, %s, %s)
  ON CONFLICT (tenant_id, intent_key) DO NOTHING
  RETURNING intent_key, draft_hash, estado, order_id, criado_at
"""

#: O `INSERT` do espelho, como o `inserirNoTenant` o constroi para a fase 2. O
#: `numero_publico` **nao** se passa: e o `DEFAULT platform.order_numero_publico()`
#: da coluna, e passa-lo aqui era o ensaio a provar um numero que ele escolheu.
SQL_ESCREVER_ESPELHO = """
  INSERT INTO platform.orders_mirror
         (tenant_id, contact_id, origem, intent_key, confirmacao_dono,
          total_minor, currency, lines_snapshot, entrega_modo)
  VALUES (%s, %s, 'pme', %s, %s, %s, 'AOA', %s, 'levantamento')
  RETURNING id, numero_publico, estado, version
"""


def _hash(texto: str) -> bytes:
    """Um `draft_hash` de 32 octetos, que e o que o `CHECK` da `0030` exige.

    **Nao e a derivacao do modulo**, e nao finge ser: a canonicalizacao das
    linhas e o `SHA-256(linhas || entrega_modo)` medem-se em
    `services/com/tests/orders.intents.test.ts`, onde sao funcoes puras. O que
    esta suite precisa e de dois valores de 32 octetos que sejam iguais entre si
    quando o rascunho e o mesmo e diferentes quando nao e — e o que ela mede e o
    **protocolo** que os compara, nao a formula que os produz. Derivar aqui a
    formula outra vez era criar uma segunda fonte para ela, que e o defeito que
    o `consultas.py` desta suite existe para evitar.
    """
    return hashlib.sha256(texto.encode("utf-8")).digest()


def _chave(sufixo: str = "") -> str:
    """Uma `intent_key` com a forma da do modulo: 26 caracteres de Crockford.

    A derivacao (HMAC com o segredo do cofre) mede-se em TypeScript, pela razao
    do `_hash`. O que conta aqui e o comprimento e o alfabeto, para que o que a
    suite insere seja indistinguivel do que o modulo insere.
    """
    alfabeto = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    bruto = hashlib.sha256(f"{uuid.uuid4().hex}{sufixo}".encode()).digest()
    saida = ""
    acumulado = 0
    bits = 0
    for octeto in bruto:
        acumulado = (acumulado << 8) | octeto
        bits += 8
        while bits >= 5:
            bits -= 5
            saida += alfabeto[(acumulado >> bits) & 31]
            if len(saida) == 26:
                return saida
    raise AssertionError("nao saiu uma chave de 26 caracteres")


def _ligar_app(tenant: str):
    conexao = ligacao.ligar("app")
    cursor = conexao.cursor()
    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
    cursor.fetchone()
    return conexao, cursor


def _no_app(tenant: str, consulta, *argumentos) -> list:
    """Corre uma consulta do modulo como `kamba_app`, **confirma**, e fecha.

    **O `commit` nao e higiene: e o que impede a suite de bloquear em si mesma.**
    A primeira versao deste ficheiro abria uma ligacao por chamada e nunca
    confirmava — o `UPDATE` da primeira chamada ficava a segurar a tranca da
    linha numa transaccao aberta, e a segunda chamada, noutra ligacao, esperava
    por ela **para sempre**. Medido: a suite nao terminou em 900 s e o
    `gate_bd.py` saiu com **0**, que e o verde falso desta familia (o CAS do
    subestado foi o caso que pendurou).

    E uma ligacao **curta** e nao uma por teste pela razao que a `base.py`
    escreve para as sementes: uma transaccao aberta nao ve o que outra ainda nao
    confirmou, e as leituras desta suite tem de ver o que as escritas dela
    fizeram.
    """
    conexao, cursor = _ligar_app(tenant)
    try:
        cursor.execute(consulta.sql, consulta.args(*argumentos))
        # **`list()` e nao o que o `fetchall` devolve.** O `pg8000` devolve uma
        # **tupla** vazia quando nao ha linhas, e `() != []` em Python: oito
        # casos desta suite falharam com `AssertionError: () != []` sobre
        # consultas que estavam certas. Normaliza-se aqui, uma vez, em vez de
        # cada caso ter de saber qual das duas formas o driver escolheu.
        linhas = list(cursor.fetchall())
        conexao.commit()
        return linhas
    finally:
        conexao.close()


def _saga_noutra_ligacao(
    tenant: str,
    contacto: str,
    chave: str,
    hash_do_rascunho: bytes,
    *,
    confirmacao: str = "nao_aplicavel",
    emitir: bool = True,
    falhar_antes_do_espelho: bool = False,
):
    """A saga do §6.3 em **duas** transaccoes, numa ligacao propria.

    Devolve `("criada", numero_publico)`, `("repeticao", numero_publico)`,
    `("recusa", codigo)` ou `("erro", sqlstate)`. **Nao levanta**: o que o ensaio
    quer e a distribuicao dos desfechos, e uma excepcao a atravessar a piscina
    perdia as outras quarenta e nove.

    O `falhar_antes_do_espelho` injecta a falha do criterio 5 — entre a
    confirmacao do recibo e a escrita do espelho —, que e o ponto exacto onde o
    §6.3 poe o Registo e onde a reconciliacao do §10.3 tem de limpar.
    """
    conexao, cursor = _ligar_app(tenant)
    try:
        cursor.execute(SQL_RESERVAR_INTENCAO, (tenant, chave, hash_do_rascunho))
        nossa = cursor.fetchone() is not None
        # **A fase 1 confirma sozinha**, e e isso que torna o `em_curso`
        # observavel: com uma transaccao so, o recibo e o espelho entravam
        # juntos e o estado `em_curso` do `CHECK` da `0030` era inalcancavel.
        conexao.commit()

        if not nossa:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
            cursor.fetchone()
            cursor.execute(SQL_LER_INTENCAO.sql, SQL_LER_INTENCAO.args(tenant, [chave]))
            linha = cursor.fetchone()
            conexao.rollback()
            if linha is None:
                return "recusa", "UPSTREAM_DOWN"
            _, _, draft_hash, estado, order_id, _ = linha
            if bytes(draft_hash) != hash_do_rascunho:
                return "recusa", "INTENT_REUSED_WITH_DIFFERENT_CONTENT"
            if estado == "concluida" and order_id is not None:
                # **Na mesma ligacao e nao numa nova.** A primeira versao abria
                # outra aqui e deixava a primeira por fechar: com cinquenta
                # threads sao cinquenta ligacoes penduradas, e o PostgreSQL
                # recusa a partir do `max_connections`. O `set_config(..., true)`
                # e local a transaccao, pelo que depois do `rollback` tem de se
                # repor — e e por isso que ele aparece outra vez.
                cursor.execute(
                    "SELECT set_config('app.tenant_id', %s, true)", (tenant,)
                )
                cursor.fetchone()
                cursor.execute(
                    "SELECT numero_publico FROM platform.orders_mirror "
                    " WHERE tenant_id = %s AND id = %s",
                    (tenant, order_id),
                )
                numero = cursor.fetchone()[0]
                conexao.rollback()
                return "repeticao", str(numero)
            # `em_curso` de outra saga: o criterio 5 manda esperar <= 3 s. A
            # espera corre **fora** de transaccao, porque sob READ COMMITTED uma
            # transaccao aberta ve o mesmo recibo quantas vezes o leia.
            return "recusa", "UPSTREAM_TIMEOUT"

        if falhar_antes_do_espelho:
            # A falha injectada: o recibo fica `em_curso` e o espelho nunca
            # nasce. **E o estado que a reconciliacao do §10.3 tem de ver.**
            return "recusa", "FALHA_INJECTADA"

        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        cursor.fetchone()
        cursor.execute(
            SQL_ESCREVER_ESPELHO,
            (
                tenant,
                contacto,
                chave,
                confirmacao,
                TOTAL,
                json.dumps(LINHAS),
            ),
        )
        encomenda, numero, _, _ = cursor.fetchone()
        if emitir:
            cursor.execute(
                SQL_EMITIR.sql,
                SQL_EMITIR.args(
                    "order.created",
                    1,
                    tenant,
                    "order",
                    str(encomenda),
                    json.dumps(
                        {
                            "order_id": str(encomenda),
                            "contact_id": contacto,
                            "numero_publico": str(numero),
                            "origem": "pme",
                            "total_minor": TOTAL,
                            "currency": "AOA",
                            "entrega_modo": "levantamento",
                            "linhas": [
                                {"sku": "arroz-5kg", "qty": 1, "preco_minor": TOTAL}
                            ],
                        }
                    ),
                    "P0",
                    ["transacao"],
                ),
            )
            cursor.fetchone()
        cursor.execute(
            SQL_CONCLUIR_INTENCAO.sql,
            SQL_CONCLUIR_INTENCAO.args(tenant, chave, str(encomenda)),
        )
        if cursor.fetchone() is None:
            # O recibo nao estava `em_curso`: outra saga fechou-o entre as duas
            # fases. **Reverte inteira**, por desenho — a encomenda que acabamos
            # de escrever ficaria orfa de recibo.
            conexao.rollback()
            return "recusa", "RECIBO_FECHADO_POR_OUTRA"
        conexao.commit()
        return "criada", str(numero)
    except pg8000.dbapi.DatabaseError as erro:
        conexao.rollback()
        return "erro", sqlstate(erro)
    finally:
        conexao.close()


class TestCinquentaConcorrentes(ComEncomendas):
    """Criterio 3: 50 sagas com a mesma chave dao 1 encomenda e a mesma resposta."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.contacto = self.criar_contacto(self.tenant)

    def _contar(self, sql: str, parametros: tuple) -> int:
        self.semente.execute(sql, parametros)
        return int(self.semente.fetchone()[0])

    def test_cinquenta_sagas_com_a_mesma_chave_dao_uma_encomenda(self) -> None:
        chave = _chave()
        hash_do_rascunho = _hash("arroz-5kg:1|levantamento")

        with concurrent.futures.ThreadPoolExecutor(max_workers=SAGAS) as piscina:
            desfechos = list(
                piscina.map(
                    lambda _: _saga_noutra_ligacao(
                        self.tenant, self.contacto, chave, hash_do_rascunho
                    ),
                    range(SAGAS),
                )
            )

        criadas = [d for d in desfechos if d[0] == "criada"]
        self.assertEqual(
            len(criadas),
            1,
            f"uma saga cria e as outras {SAGAS - 1} nao: {desfechos[:5]}",
        )
        # **Uma linha em `orders_mirror`**, que e a propriedade que o criterio
        # nomeia. A unicidade `(tenant_id, intent_key)` da revisao `0030` e a
        # segunda barreira, e esta asercao e a que mostra que o protocolo nao
        # chega a precisar dela.
        self.assertEqual(
            self._contar(
                "SELECT count(*) FROM platform.orders_mirror "
                " WHERE tenant_id = %s AND intent_key = %s",
                (self.tenant, chave),
            ),
            1,
        )
        # **Um `order.created` no outbox**, e nao cinquenta. E o risco real: a
        # encomenda era uma e o evento saia por cada tentativa, com o IDX e o DAT
        # a reagir cinquenta vezes a uma venda.
        self.assertEqual(
            self._contar(
                "SELECT count(*) FROM platform.events_outbox "
                " WHERE tenant_id = %s AND tipo = 'order.created'",
                (self.tenant,),
            ),
            1,
        )
        # **Um recibo, `concluida`, a apontar para ela.**
        self.semente.execute(
            "SELECT estado, order_id FROM platform.order_intents "
            " WHERE tenant_id = %s AND intent_key = %s",
            (self.tenant, chave),
        )
        estado, order_id = self.semente.fetchone()
        self.assertEqual(estado, "concluida")
        self.assertIsNotNone(order_id)

    def test_a_resposta_e_a_mesma_para_quem_repete_depois_de_a_saga_fechar(self) -> None:
        """A segunda metade do criterio 3: «e a mesma resposta»."""
        chave = _chave()
        hash_do_rascunho = _hash("arroz-5kg:1|levantamento")
        primeiro = _saga_noutra_ligacao(
            self.tenant, self.contacto, chave, hash_do_rascunho
        )
        self.assertEqual(primeiro[0], "criada")

        repeticoes = [
            _saga_noutra_ligacao(self.tenant, self.contacto, chave, hash_do_rascunho)
            for _ in range(3)
        ]
        for desfecho in repeticoes:
            self.assertEqual(desfecho, ("repeticao", primeiro[1]))
        self.assertEqual(
            self._contar(
                "SELECT count(*) FROM platform.orders_mirror WHERE tenant_id = %s",
                (self.tenant,),
            ),
            1,
        )

    def test_a_fronteira_da_janela_e_a_mesma_chave_e_da_uma_encomenda(self) -> None:
        """Criterio 3: «duas chamadas as 14:04:59 e 14:05:01 produzem 1».

        **A metade que esta aqui e a que depende das transaccoes.** Que a chave e
        a **mesma** nos dois instantes nao se mede contra uma base de dados: e
        uma propriedade da derivacao, porque nenhuma das quatro partes do §6.3 e
        tempo, e mede-se em `orders.intents.test.ts` («a mesma intencao em dois
        instantes da a mesma intent_key»). O que esta metade mostra e que, dada a
        mesma chave, as duas chamadas produzem **uma** encomenda — e e por isso
        que os dois instantes aparecem no nome deste ensaio sem o relogio entrar
        em sitio nenhum: o relogio nao entra, e **essa** e a propriedade.

        A chave do documento exploratorio (`hash(msisdn + sku + janela_5min)`)
        falhava aqui pelo outro lado: dava duas chaves, e nenhuma barreira de
        base de dados podia juntar o que a derivacao separou.
        """
        chave = _chave()
        hash_do_rascunho = _hash("arroz-5kg:1|levantamento")
        as_04_59 = _saga_noutra_ligacao(
            self.tenant, self.contacto, chave, hash_do_rascunho
        )
        as_05_01 = _saga_noutra_ligacao(
            self.tenant, self.contacto, chave, hash_do_rascunho
        )
        self.assertEqual(as_04_59[0], "criada")
        self.assertEqual(as_05_01, ("repeticao", as_04_59[1]))
        self.assertEqual(
            self._contar(
                "SELECT count(*) FROM platform.orders_mirror WHERE tenant_id = %s",
                (self.tenant,),
            ),
            1,
        )

    def test_a_chave_primaria_do_recibo_recusa_o_segundo_com_23505(self) -> None:
        """O canario da chave primaria de `order_intents`, e **so** dela.

        Sem isto, as asercoes acima ficavam verdes com o protocolo a funcionar e
        a barreira da base por provar — e sao **duas** barreiras independentes, e
        o Contexto do bloco di-lo por extenso.

        **O que este caso NAO mede**, e a revisao adversarial apanhou-o: a
        unicidade que impede a segunda **encomenda** e a
        `orders_mirror_intent_uq`, nao esta. Esta impede o segundo **recibo**,
        que e outra propriedade. A outra esta na
        `TestOTravaoDeUltimoRecurso`.
        """
        chave = _chave()
        self.semente.execute(
            "INSERT INTO platform.order_intents (tenant_id, intent_key, draft_hash) "
            "VALUES (%s, %s, %s)",
            (self.tenant, chave, _hash("x")),
        )
        estado = self.tentar(
            "INSERT INTO platform.order_intents (tenant_id, intent_key, draft_hash) "
            "VALUES (%s, %s, %s)",
            (self.tenant, chave, _hash("y")),
        )
        self.assertEqual(estado, "23505")


class TestConteudoDiferenteEChavesNovas(ComEncomendas):
    """Criterio 4: o conteudo diferente, a recompra e o carrinho editado."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.contacto = self.criar_contacto(self.tenant)

    def _encomendas(self) -> int:
        self.semente.execute(
            "SELECT count(*) FROM platform.orders_mirror WHERE tenant_id = %s",
            (self.tenant,),
        )
        return int(self.semente.fetchone()[0])

    def test_a_mesma_chave_com_draft_hash_diferente_e_recusada(self) -> None:
        chave = _chave()
        primeiro = _saga_noutra_ligacao(
            self.tenant, self.contacto, chave, _hash("arroz-5kg:1|levantamento")
        )
        self.assertEqual(primeiro[0], "criada")
        segundo = _saga_noutra_ligacao(
            self.tenant, self.contacto, chave, _hash("arroz-5kg:2|levantamento")
        )
        self.assertEqual(segundo, ("recusa", "INTENT_REUSED_WITH_DIFFERENT_CONTENT"))
        # **E nao cria nada**, que e a parte do criterio que importa: a recusa e
        # antes de qualquer escrita.
        self.assertEqual(self._encomendas(), 1)

    def test_o_conteudo_diferente_recusa_antes_de_esperar_pelo_em_curso(self) -> None:
        """O `draft_hash` compara-se **antes** do estado.

        Um recibo `em_curso` com conteudo diferente nao e uma saga a correr para
        este pedido: esperar por ela tres segundos era esperar pelo trabalho de
        outro rascunho para depois recusar de qualquer forma.
        """
        chave = _chave()
        abandonado = _saga_noutra_ligacao(
            self.tenant,
            self.contacto,
            chave,
            _hash("arroz-5kg:1|levantamento"),
            falhar_antes_do_espelho=True,
        )
        self.assertEqual(abandonado, ("recusa", "FALHA_INJECTADA"))
        outro = _saga_noutra_ligacao(
            self.tenant, self.contacto, chave, _hash("sabao-azul:1|entrega")
        )
        self.assertEqual(outro, ("recusa", "INTENT_REUSED_WITH_DIFFERENT_CONTENT"))

    def test_a_recompra_com_chave_nova_cria_encomenda_nova(self) -> None:
        """«Recompra do mesmo SKU 30 s depois (novo `draft_id`) cria nova.»

        O rascunho e **o mesmo** — mesmo SKU, mesma quantidade, mesmo
        `draft_hash` — e a chave e outra, porque o `draft_id` e outro. E a
        propriedade que a chave por janela temporal destruia: dentro dos cinco
        minutos, a recompra era a mesma chave e o cliente nao conseguia comprar
        outra vez.
        """
        hash_do_rascunho = _hash("arroz-5kg:1|levantamento")
        primeira = _saga_noutra_ligacao(
            self.tenant, self.contacto, _chave("d1"), hash_do_rascunho
        )
        segunda = _saga_noutra_ligacao(
            self.tenant, self.contacto, _chave("d2"), hash_do_rascunho
        )
        self.assertEqual(primeira[0], "criada")
        self.assertEqual(segunda[0], "criada")
        self.assertNotEqual(primeira[1], segunda[1])
        self.assertEqual(self._encomendas(), 2)

    def test_o_carrinho_editado_com_versao_nova_cria_encomenda_distinta(self) -> None:
        """«Carrinho editado (nova `draft_version`) cria encomenda distinta.»"""
        primeira = _saga_noutra_ligacao(
            self.tenant, self.contacto, _chave("v1"), _hash("arroz-5kg:1|levantamento")
        )
        segunda = _saga_noutra_ligacao(
            self.tenant, self.contacto, _chave("v2"), _hash("arroz-5kg:3|levantamento")
        )
        self.assertEqual(primeira[0], "criada")
        self.assertEqual(segunda[0], "criada")
        self.assertNotEqual(primeira[1], segunda[1])
        self.assertEqual(self._encomendas(), 2)


class TestFalhaERetoma(ComEncomendas):
    """Criterio 5: a falha injectada, a retoma aos dois minutos, a espera."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.contacto = self.criar_contacto(self.tenant)
        self.chave = _chave()
        self.hash = _hash("arroz-5kg:1|levantamento")

    def _recibo(self) -> tuple[str, object]:
        self.semente.execute(
            "SELECT estado, order_id FROM platform.order_intents "
            " WHERE tenant_id = %s AND intent_key = %s",
            (self.tenant, self.chave),
        )
        estado, order_id = self.semente.fetchone()
        return str(estado), order_id

    def _envelhecer(self, minutos: int) -> None:
        """Recua o `criado_at` do recibo. **Pelo administrador**, de proposito.

        O `UPDATE_DA_APP_EM_INTENCOES` da revisao `0030` da ao `kamba_app` duas
        colunas — `estado` e `order_id` — e o `criado_at` **nao** e uma delas. E
        a barreira certa: o instante da criacao de um recibo nao e de quem o
        retoma. Por isso o ensaio envelhece a linha com privilegio, que e o que
        o tempo faria.
        """
        self.semente.execute(
            "UPDATE platform.order_intents SET criado_at = now() - %s::interval "
            " WHERE tenant_id = %s AND intent_key = %s",
            (f"{minutos} minutes", self.tenant, self.chave),
        )

    def test_a_falha_injectada_deixa_o_recibo_em_curso_e_sem_espelho(self) -> None:
        """A falha do criterio 5, no ponto onde o §6.3 poe o Registo.

        E este estado que a reconciliacao do §10.3 (KAM-044) tem de ver: um
        recibo sem encomenda. Sem a saga em **duas** transaccoes ele era
        inalcancavel — ver a nota do modulo.
        """
        desfecho = _saga_noutra_ligacao(
            self.tenant,
            self.contacto,
            self.chave,
            self.hash,
            falhar_antes_do_espelho=True,
        )
        self.assertEqual(desfecho, ("recusa", "FALHA_INJECTADA"))
        self.assertEqual(self._recibo(), ("em_curso", None))
        self.semente.execute(
            "SELECT count(*) FROM platform.orders_mirror "
            " WHERE tenant_id = %s AND intent_key = %s",
            (self.tenant, self.chave),
        )
        self.assertEqual(int(self.semente.fetchone()[0]), 0)

    def test_um_em_curso_recente_nao_se_retoma(self) -> None:
        """A barreira dos dois minutos, pelo lado que protege.

        Retomar por cima de uma saga **viva** e o que duplica o efeito: ela pode
        estar a meio da chamada ao Registo. Por isso a retoma tem o instante no
        predicado e nao so o estado.
        """
        _saga_noutra_ligacao(
            self.tenant,
            self.contacto,
            self.chave,
            self.hash,
            falhar_antes_do_espelho=True,
        )
        limite = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=MINUTOS_PARA_RETOMAR)
        self.assertEqual(
            _no_app(self.tenant, SQL_FALHAR_INTENCAO, self.tenant, self.chave, limite),
            [],
        )
        self.assertEqual(self._recibo()[0], "em_curso")

    def test_um_em_curso_de_mais_de_dois_minutos_marca_se_falhada_e_retoma_se(self) -> None:
        """«Intencao `em_curso` > 2 min e retomada ou marcada `falhada`.»

        Sao **duas** instrucoes e nao uma, e cada uma tem o estado esperado no
        predicado: de N concorrentes passa **uma**.
        """
        _saga_noutra_ligacao(
            self.tenant,
            self.contacto,
            self.chave,
            self.hash,
            falhar_antes_do_espelho=True,
        )
        self._envelhecer(MINUTOS_PARA_RETOMAR + 1)
        limite = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=MINUTOS_PARA_RETOMAR)
        self.assertEqual(
            len(
                _no_app(
                    self.tenant, SQL_FALHAR_INTENCAO, self.tenant, self.chave, limite
                )
            ),
            1,
        )
        self.assertEqual(self._recibo()[0], "falhada")

        self.assertEqual(
            len(_no_app(self.tenant, SQL_RETOMAR_INTENCAO, self.tenant, self.chave)),
            1,
        )
        self.assertEqual(self._recibo()[0], "em_curso")

    def test_de_oito_retomas_concorrentes_passa_uma(self) -> None:
        """A razao de a retoma ser um `UPDATE` condicional.

        Dois leitores de um recibo `falhada` liam os dois `falhada` e corriam os
        dois a saga. O `WHERE estado = 'falhada'` deixa passar um — e e a mesma
        licao que o `idempotency.py` da TLS escreveu para a barreira do outro
        lado.
        """
        self.semente.execute(
            "INSERT INTO platform.order_intents "
            "       (tenant_id, intent_key, draft_hash, estado) "
            "VALUES (%s, %s, %s, 'falhada')",
            (self.tenant, self.chave, self.hash),
        )

        def _retomar(_):
            conexao, cursor = _ligar_app(self.tenant)
            try:
                cursor.execute(
                    SQL_RETOMAR_INTENCAO.sql,
                    SQL_RETOMAR_INTENCAO.args(self.tenant, self.chave),
                )
                ganhou = cursor.fetchone() is not None
                conexao.commit()
                return ganhou
            finally:
                conexao.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as piscina:
            ganhos = list(piscina.map(_retomar, range(8)))
        self.assertEqual(sum(1 for g in ganhos if g), 1, ganhos)

    def test_o_recibo_em_curso_passa_a_concluida_e_e_isso_que_a_espera_observa(self) -> None:
        """«`em_curso` concorrente aguarda <= 3 s e devolve a mesma resposta.»

        O que esta aqui e o **estado** que a espera observa, e nao a espera: ela
        e um laco de leituras fora de transaccao, e o que decide o desfecho e o
        recibo passar de `em_curso` a `concluida`. Mede-se as duas pontas: com o
        recibo `em_curso` a leitura nao da encomenda nenhuma, e depois de fechar
        da a mesma que o vencedor escreveu.
        """
        self.semente.execute(
            "INSERT INTO platform.order_intents "
            "       (tenant_id, intent_key, draft_hash) VALUES (%s, %s, %s)",
            (self.tenant, self.chave, self.hash),
        )
        linha = _no_app(self.tenant, SQL_LER_INTENCAO, self.tenant, [self.chave])[0]
        self.assertEqual(linha[3], "em_curso")
        self.assertIsNone(linha[4])

        encomenda = self.criar_encomenda(
            self.tenant, self.contacto, intent_key=f"{self.chave}-outra"
        )
        self.semente.execute(
            "UPDATE platform.order_intents SET estado = 'concluida', order_id = %s "
            " WHERE tenant_id = %s AND intent_key = %s",
            (encomenda, self.tenant, self.chave),
        )
        linha = _no_app(self.tenant, SQL_LER_INTENCAO, self.tenant, [self.chave])[0]
        self.assertEqual(linha[3], "concluida")
        self.assertEqual(str(linha[4]), encomenda)

    def test_o_recibo_concluido_exige_a_encomenda_nos_dois_sentidos(self) -> None:
        """O `order_intents_concluida_exige_encomenda_ck` da revisao `0030`.

        E a barreira que impede o que o `SQL_CONCLUIR_INTENCAO` nao poderia
        impedir sozinho: um recibo `concluida` sem encomenda nao e recibo de
        nada, e uma encomenda num recibo `em_curso` dizia que a saga nao acabou
        com a prova de que acabou.
        """
        self.semente.execute(
            "INSERT INTO platform.order_intents "
            "       (tenant_id, intent_key, draft_hash) VALUES (%s, %s, %s)",
            (self.tenant, self.chave, self.hash),
        )
        self.assertEqual(
            self.tentar(
                "UPDATE platform.order_intents SET estado = 'concluida' "
                " WHERE tenant_id = %s AND intent_key = %s",
                (self.tenant, self.chave),
            ),
            "23514",
        )
        encomenda = self.criar_encomenda(self.tenant, self.contacto)
        self.assertEqual(
            self.tentar(
                "UPDATE platform.order_intents SET order_id = %s "
                " WHERE tenant_id = %s AND intent_key = %s",
                (encomenda, self.tenant, self.chave),
            ),
            "23514",
        )


class TestPedidoPorPagar(ComEncomendas):
    """Criterio 8: o facto «ja tem o pedido K7H3Q9 por pagar». Nunca bloqueia."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.contacto = self.criar_contacto(self.tenant)
        self.hash = _hash("arroz-5kg:1|levantamento")

    def _semear(self, chave: str, *, estado: str = "criada", minutos: int = 0) -> str:
        encomenda = self.criar_encomenda(self.tenant, self.contacto, intent_key=chave)
        if estado != "criada":
            self.levar_a(self.tenant, encomenda, estado)
        self.semente.execute(
            "INSERT INTO platform.order_intents "
            "       (tenant_id, intent_key, draft_hash, estado, order_id) "
            "VALUES (%s, %s, %s, 'concluida', %s)",
            (self.tenant, chave, self.hash, encomenda),
        )
        if minutos:
            self.semente.execute(
                "UPDATE platform.orders_mirror SET criado_at = now() - %s::interval "
                " WHERE tenant_id = %s AND id = %s",
                (f"{minutos} minutes", self.tenant, encomenda),
            )
        return encomenda

    def _consultar(self, chave_actual: str, contacto: str | None = None):
        desde = dt.datetime.now(dt.UTC) - dt.timedelta(
            minutes=MINUTOS_DO_PEDIDO_POR_PAGAR
        )
        return _no_app(
            self.tenant,
            SQL_PEDIDO_POR_PAGAR,
            self.tenant,
            self.hash,
            self.contacto if contacto is None else contacto,
            desde,
            chave_actual,
        )

    def test_um_pedido_criado_ha_pouco_aparece_como_facto(self) -> None:
        anterior = self._semear(_chave("anterior"), minutos=5)
        linhas = self._consultar(_chave("agora"))
        self.assertEqual(len(linhas), 1)
        self.assertEqual(str(linhas[0][0]), anterior)
        # O `numero_publico` e o que o facto cita ao cliente («ja tem o pedido
        # K7H3Q9 por pagar»): oito caracteres de Crockford.
        self.assertRegex(str(linhas[0][1]), r"^[0-9A-HJKMNP-TV-Z]{1,8}$")

    def test_o_proprio_recibo_nao_aparece_como_pedido_por_pagar(self) -> None:
        """O `$5` da consulta, e a razao por que ele faz falta.

        Na repeticao de um toque, o recibo desta intencao ja esta `concluida` e
        apontaria para a encomenda que acabamos de devolver — o que dizia ao
        cliente que tem por pagar o pedido que ele esta a fazer agora.
        """
        chave = _chave("mesma")
        self._semear(chave, minutos=1)
        self.assertEqual(self._consultar(chave), [])

    def test_as_tres_fronteiras_do_criterio_oito(self) -> None:
        """Mais de 30 min, estado pago e outro contacto nao sao «por pagar»."""
        # Fora da janela. A fronteira entra como argumento para que ela se escreva
        # como uma comparacao exacta em vez de se dormir trinta minutos.
        self._semear(_chave("velho"), minutos=MINUTOS_DO_PEDIDO_POR_PAGAR + 1)
        self.assertEqual(self._consultar(_chave("agora")), [])

        # Ja paga: nao e um pedido por pagar, e dizer ao cliente que tem um
        # pedido que ja pagou era pior do que nao dizer nada.
        self._semear(_chave("paga"), estado="paga", minutos=1)
        self.assertEqual(self._consultar(_chave("agora")), [])

        # Cancelada: tambem nao. Os tres estados sao os de antes do dinheiro.
        self._semear(_chave("cancelada"), estado="cancelada", minutos=1)
        self.assertEqual(self._consultar(_chave("agora")), [])

        # De outro contacto do mesmo tenant: nao e dele.
        outro = self.criar_contacto(self.tenant)
        self._semear(_chave("doutro"), minutos=1)
        self.assertEqual(self._consultar(_chave("agora"), contacto=outro), [])

    def test_um_aguarda_pagamento_conta_como_por_pagar(self) -> None:
        """O caso central do criterio: a referencia emitida e nao paga."""
        encomenda = self._semear(_chave("aguarda"), estado="aguarda_pagamento", minutos=2)
        linhas = self._consultar(_chave("agora"))
        self.assertEqual(len(linhas), 1)
        self.assertEqual(str(linhas[0][0]), encomenda)
        self.assertEqual(linhas[0][2], "aguarda_pagamento")

    def test_um_draft_hash_diferente_nao_e_o_mesmo_pedido(self) -> None:
        self._semear(_chave("outro-rascunho"), minutos=1)
        desde = dt.datetime.now(dt.UTC) - dt.timedelta(
            minutes=MINUTOS_DO_PEDIDO_POR_PAGAR
        )
        self.assertEqual(
            _no_app(
                self.tenant,
                SQL_PEDIDO_POR_PAGAR,
                self.tenant,
                _hash("sabao-azul:9|entrega"),
                self.contacto,
                desde,
                _chave(),
            ),
            [],
        )


class TestConfirmacaoDoDono(ComEncomendas):
    """Criterio 7: `pendente` sem referencia nem reserva, e o CAS do subestado."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.contacto = self.criar_contacto(self.tenant)
        self.encomenda = self.criar_encomenda(
            self.tenant, self.contacto, confirmacao_dono="pendente"
        )

    def _escrever(self, de: str, para: str):
        return _no_app(
            self.tenant,
            SQL_CONFIRMACAO_DO_DONO,
            self.tenant,
            self.encomenda,
            para,
            de,
        )

    def test_a_encomenda_do_confirmar_dono_fica_criada_e_pendente(self) -> None:
        """«Deixa a encomenda `criada` com `confirmacao_dono='pendente'`.»"""
        estado, versao = self.estado_de(self.encomenda)
        self.assertEqual(estado, "criada")
        self.assertEqual(versao, 1)
        self.semente.execute(
            "SELECT confirmacao_dono FROM platform.orders_mirror WHERE id = %s",
            (self.encomenda,),
        )
        self.assertEqual(self.semente.fetchone()[0], "pendente")

    def test_sem_referencia_e_sem_reserva(self) -> None:
        """A segunda metade do criterio 7, e a que e facil tratar como opcional.

        **Sem referencia:** a encomenda nao chega a `aguarda_pagamento`, que e o
        estado onde a referencia vive — a `version` fica em 1 e o
        `order_state_log` dela esta vazio. **Sem reserva:** nao ha nenhuma linha
        de `platform.stock_reservations` para esta encomenda.

        ## A asercao da segunda metade mudou, e a mudanca estava escrita aqui

        Ate a revisao `0033` (KAM-045) este caso afirmava «sem reserva» pela
        **ausencia da tabela**, porque a tabela nao existia — e a propria
        asercao levava a mensagem que mandava substitui-la quando existisse, com
        o credor nomeado. A tabela existe desde o KAM-045, pelo que a asercao
        passa a ser a que o criterio 7 do KAM-046 queria: **zero reservas para
        esta encomenda**.

        A diferenca nao e cosmetica. «A tabela nao existe» era verdadeira por
        uma razao que nada tem a ver com o criterio — nenhuma encomenda teria
        reserva, porque reserva nenhuma era possivel —, e deixaria de medir o
        criterio no instante em que a tabela aparecesse: passaria a falhar, que
        e o que a mensagem previa. «Esta encomenda tem zero reservas» mede o
        que o criterio diz, e e **falsificavel**: um `confirmar_dono` que
        reservasse stock antes da confirmacao do dono fa-la-ia subir a um.

        E e o que os *Detalhes Tecnicos* do bloco KAM-045 escrevem do outro
        lado: «itens `confirmar_dono` so reservam depois de
        `confirmacao_dono='confirmada'`». Este caso e a metade do KAM-046 dessa
        regra, agora medida contra a tabela que a sustenta.
        """
        self.semente.execute(
            "SELECT count(*) FROM platform.order_state_log "
            " WHERE tenant_id = %s AND order_id = %s",
            (self.tenant, self.encomenda),
        )
        self.assertEqual(int(self.semente.fetchone()[0]), 0)
        self.semente.execute(
            "SELECT count(*) FROM platform.stock_reservations "
            " WHERE tenant_id = %s AND order_id = %s",
            (self.tenant, self.encomenda),
        )
        self.assertEqual(
            int(self.semente.fetchone()[0]),
            0,
            "um item `confirmar_dono` so reserva depois de a confirmacao do "
            "dono ser `confirmada`: com ela `pendente`, a encomenda nao tem "
            "reserva nenhuma",
        )

    def test_o_cas_do_subestado_passa_uma_vez_e_o_segundo_nao_encontra(self) -> None:
        self.assertEqual(len(self._escrever("pendente", "confirmada")), 1)
        # O segundo, com o mesmo `de`, nao encontra a linha: e o conflito que o
        # modulo traduz numa releitura. Dois cliques no mesmo botao do dono dao
        # uma escrita.
        self.assertEqual(self._escrever("pendente", "confirmada"), [])
        self.semente.execute(
            "SELECT confirmacao_dono FROM platform.orders_mirror WHERE id = %s",
            (self.encomenda,),
        )
        self.assertEqual(self.semente.fetchone()[0], "confirmada")

    def test_escrever_o_subestado_nao_muda_o_estado_nem_a_version(self) -> None:
        """Nao dispara o *trigger* diferido, e e por isso que nao ha registo.

        O `order_estado_exige_log` devolve `NULL` quando o estado nao muda, e o
        `order_transicao_valida` so consulta o grafo numa mudanca de estado. Se
        algum deles disparasse, esta instrucao levantava `KA005` — e a asercao
        da `version` e a que mostra que ela **nao** e uma transicao.
        """
        self._escrever("pendente", "recusada")
        self.assertEqual(self.estado_de(self.encomenda), ("criada", 1))

    def test_um_subestado_fora_dos_cinco_e_recusado_pela_base(self) -> None:
        self.assertEqual(
            self.tentar(
                "UPDATE platform.orders_mirror SET confirmacao_dono = 'talvez' "
                " WHERE tenant_id = %s AND id = %s",
                (self.tenant, self.encomenda),
            ),
            "23514",
        )

    def test_depois_de_cancelada_o_subestado_ja_nao_se_escreve(self) -> None:
        """O `estado = 'criada'` no predicado, e a ordem que ele impoe.

        E por isto que o modulo escreve a coluna **antes** de cancelar: depois do
        cancelamento o `UPDATE` nao encontra a linha, e uma encomenda cancelada
        com `confirmacao_dono='pendente'` dizia a quem a lesse que ainda esperava
        pelo dono.
        """
        self.transitar(
            self.tenant, self.encomenda, "criada", "cancelada", 1, "dono_recusa"
        )
        self.assertEqual(self._escrever("pendente", "recusada"), [])
        confirmacao, estado, _ = _no_app(
            self.tenant, SQL_LER_CONFIRMACAO, self.tenant, self.encomenda
        )[0]
        self.assertEqual((confirmacao, estado), ("pendente", "cancelada"))


class TestIsolamentoDaIntencao(ComEncomendas):
    """ISO: a `intent_key` de A nunca resolve a encomenda de B."""

    def setUp(self) -> None:
        super().setUp()
        self.a = self.criar_tenant()
        self.b = self.criar_tenant()
        self.contacto_a = self.criar_contacto(self.a)
        self.contacto_b = self.criar_contacto(self.b)
        self.chave = _chave("partilhada")
        self.hash = _hash("arroz-5kg:1|levantamento")

    def test_a_mesma_intent_key_em_dois_tenants_sao_dois_recibos(self) -> None:
        """A unicidade e `(tenant_id, intent_key)` e nao `intent_key`.

        E o ISO-33..38 noutra coluna: o mesmo texto de chave em dois tenants sao
        duas linhas independentes, e **nenhum ve a do outro**.
        """
        for tenant, contacto in ((self.a, self.contacto_a), (self.b, self.contacto_b)):
            desfecho = _saga_noutra_ligacao(tenant, contacto, self.chave, self.hash)
            self.assertEqual(desfecho[0], "criada", tenant)

        linhas = _no_app(self.a, SQL_LER_INTENCAO, self.a, [self.chave])
        self.assertEqual(len(linhas), 1)
        self.assertEqual(str(linhas[0][0]), self.a)

    def test_a_intent_key_de_a_nao_resolve_a_encomenda_de_b(self) -> None:
        """A asercao central do isolamento desta chave.

        Com o `ctx` de A e a chave que **so** B tem, a leitura devolve zero
        linhas — pela RLS `FORCE` e pelo `tenant_id = $1` que o repo-base exige.
        Nunca a linha de B.
        """
        chave_de_b = _chave("so-do-b")
        self.assertEqual(
            _saga_noutra_ligacao(self.b, self.contacto_b, chave_de_b, self.hash)[0],
            "criada",
        )
        self.assertEqual(_no_app(self.a, SQL_LER_INTENCAO, self.a, [chave_de_b]), [])

        # E a sonda positiva, sem a qual «zero linhas» nao prova nada: a mesma
        # consulta com o `ctx` de B **encontra**. Quatro zeros contra uma leitura
        # que nunca devolve nada ficam verdes sem RLS nenhuma.
        self.assertEqual(
            len(_no_app(self.b, SQL_LER_INTENCAO, self.b, [chave_de_b])), 1
        )

    def test_o_pedido_por_pagar_de_b_nao_chega_a_a(self) -> None:
        """O facto do criterio 8 nao atravessa tenants."""
        chave_de_b = _chave("por-pagar-de-b")
        encomenda = self.criar_encomenda(self.b, self.contacto_b, intent_key=chave_de_b)
        self.semente.execute(
            "INSERT INTO platform.order_intents "
            "       (tenant_id, intent_key, draft_hash, estado, order_id) "
            "VALUES (%s, %s, %s, 'concluida', %s)",
            (self.b, chave_de_b, self.hash, encomenda),
        )
        desde = dt.datetime.now(dt.UTC) - dt.timedelta(
            minutes=MINUTOS_DO_PEDIDO_POR_PAGAR
        )
        self.assertEqual(
            _no_app(
                self.a,
                SQL_PEDIDO_POR_PAGAR,
                self.a,
                self.hash,
                self.contacto_b,
                desde,
                _chave(),
            ),
            [],
        )


class TestOTravaoDeUltimoRecurso(ComEncomendas):
    """A `orders_mirror_intent_uq` e a leitura que a torna uma resposta.

    **Esta classe nasceu de tres achados da revisao adversarial**, e os tres sao
    o mesmo mecanismo visto de tres lados:

    * o `criado_at` **nao se reescreve** (o `UPDATE_DA_APP_EM_INTENCOES` da
      revisao `0030` da ao `kamba_app` duas colunas, e ele nao e uma delas),
      pelo que um recibo retomado continua a parecer velho e um segundo chamador
      pode falha-lo e retoma-lo por cima de uma saga viva;
    * quem as separa e a `orders_mirror_intent_uq` — a «segunda barreira
      independente» que o Contexto do bloco nomeia —, e **nenhum caso a
      exercitava**: o canario da unicidade media a chave primaria do
      `order_intents`, que e outra coisa;
    * e ela chegava como `23505`, isto e, como **excepcao** fora do `Resultado`
      que a operacao promete. O `SQL_ENCOMENDA_DA_CHAVE` e o que a transforma
      numa resposta: quem perde a corrida rele a encomenda do vencedor.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.contacto = self.criar_contacto(self.tenant)
        self.chave = _chave()
        self.hash = _hash("arroz-5kg:1|levantamento")

    def test_um_recibo_retomado_continua_a_parecer_velho(self) -> None:
        """O achado, reproduzido: a guarda da idade vale **uma** vez.

        E o caso que a secao de verificacao deste bloco cita, e o que ele mede e
        o **limite** e nao a propriedade: depois de uma retoma, o
        `SQL_FALHAR_INTENCAO` volta a encontrar a linha, porque o predicado dele
        e o estado **e a idade** e a idade nao se reescreve. A primeira versao
        desta suite afirmava que isso era inofensivo; nao e, e o que o fecha e o
        travao de baixo e nao esta cadeia.
        """
        self.semente.execute(
            "INSERT INTO platform.order_intents "
            "       (tenant_id, intent_key, draft_hash) VALUES (%s, %s, %s)",
            (self.tenant, self.chave, self.hash),
        )
        self.semente.execute(
            "UPDATE platform.order_intents SET criado_at = now() - '3 minutes'::interval"
            " WHERE tenant_id = %s AND intent_key = %s",
            (self.tenant, self.chave),
        )
        limite = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=MINUTOS_PARA_RETOMAR)

        # Primeira retoma: falha e reabre.
        self.assertEqual(
            len(_no_app(self.tenant, SQL_FALHAR_INTENCAO, self.tenant, self.chave, limite)),
            1,
        )
        self.assertEqual(
            len(_no_app(self.tenant, SQL_RETOMAR_INTENCAO, self.tenant, self.chave)),
            1,
        )

        # **E a segunda encontra-a outra vez**, com a saga da primeira a correr.
        self.assertEqual(
            len(_no_app(self.tenant, SQL_FALHAR_INTENCAO, self.tenant, self.chave, limite)),
            1,
            "a guarda da idade so vale ate a primeira retoma: e o limite dito "
            "no SQL_FALHAR_INTENCAO, e quem fecha o caso e a unicidade do "
            "espelho mais o SQL_ENCOMENDA_DA_CHAVE",
        )

    def test_a_unicidade_do_espelho_recusa_a_segunda_encomenda_da_mesma_chave(self) -> None:
        """O canario que faltava: a `orders_mirror_intent_uq`, e nao a PK do recibo.

        E **esta** a barreira que impede a segunda encomenda, e o canario antigo
        media a chave primaria do `order_intents` — que impede o segundo recibo,
        que e outra propriedade.
        """
        self.criar_encomenda(self.tenant, self.contacto, intent_key=self.chave)
        outro = self.criar_contacto(self.tenant)
        estado = self.tentar(
            "INSERT INTO platform.orders_mirror "
            "       (tenant_id, contact_id, intent_key, total_minor, lines_snapshot) "
            "VALUES (%s, %s, %s, %s, %s)",
            (self.tenant, outro, self.chave, TOTAL, json.dumps(LINHAS)),
        )
        self.assertEqual(estado, "23505")

    def test_a_leitura_pela_chave_devolve_a_encomenda_do_vencedor(self) -> None:
        """O `SQL_ENCOMENDA_DA_CHAVE`: o que transforma o `23505` numa resposta."""
        encomenda = self.criar_encomenda(
            self.tenant, self.contacto, intent_key=self.chave
        )
        linhas = _no_app(
            self.tenant, SQL_ENCOMENDA_DA_CHAVE, self.tenant, self.chave
        )
        self.assertEqual(len(linhas), 1)
        self.assertEqual(str(linhas[0][0]), encomenda)
        # As oito colunas que a resposta precisa, pela ordem da cadeia.
        self.assertEqual(len(linhas[0]), 8)
        self.assertEqual(linhas[0][2], "criada")

    def test_a_leitura_pela_chave_nao_atravessa_tenants(self) -> None:
        """Com a sonda positiva ao lado, pela razao de sempre."""
        outro_tenant = self.criar_tenant()
        contacto = self.criar_contacto(outro_tenant)
        self.criar_encomenda(outro_tenant, contacto, intent_key=self.chave)
        self.assertEqual(
            _no_app(self.tenant, SQL_ENCOMENDA_DA_CHAVE, self.tenant, self.chave),
            [],
        )
        self.assertEqual(
            len(
                _no_app(
                    outro_tenant, SQL_ENCOMENDA_DA_CHAVE, outro_tenant, self.chave
                )
            ),
            1,
        )

    def test_uma_encomenda_sob_soft_delete_nao_se_le_pela_chave(self) -> None:
        """O `deleted_at IS NULL` do predicado (§5.6)."""
        encomenda = self.criar_encomenda(
            self.tenant, self.contacto, intent_key=self.chave
        )
        self.semente.execute(
            "UPDATE platform.orders_mirror SET deleted_at = now() WHERE id = %s",
            (encomenda,),
        )
        self.assertEqual(
            _no_app(self.tenant, SQL_ENCOMENDA_DA_CHAVE, self.tenant, self.chave),
            [],
        )
