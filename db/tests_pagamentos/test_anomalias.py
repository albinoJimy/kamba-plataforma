"""A porta de escrita dos sinais de anomalia (KAM-060).

## O que so aqui se prova, e nenhuma base falsa pode

    privilegio   o `kamba_app` **nao** consegue chamar a funcao (`42501`) e o
                 `kamba_batch` consegue. E a propriedade que faz desta revisao
                 uma que *preserva* a decisao da `0032` em vez de a desfazer, e
                 um duplo de teste nao tem papeis
    INSERT       nem o `kamba_app` nem o `kamba_batch` conseguem `INSERT`
                 directo em `fraud_signals` **depois** desta revisao: o
                 `EXECUTE` nao se tornou o `INSERT` que a `0032` recusou
    regra        a lista fechada mora na funcao, porque a coluna `regra` nao tem
                 `CHECK` — o que se mede com um `INSERT` do superutilizador, que
                 **passa**, contra a funcao, que recusa
    M-3          as duas regras do `manual_confirmar` sao recusadas por aqui
    PII          um `detalhe` com chave de PII e recusado, **a qualquer
                 profundidade**
    janela       o mesmo sinal duas vezes da uma linha e devolve o mesmo `id`
    RLS          o sinal de A invisivel no contexto de B, com a funcao a correr
                 `SECURITY DEFINER` — isto e, a prova de que o `DEFINER` nao
                 contorna o `FORCE`

## As duas listas de regras sao confrontadas contra a funcao INSTALADA

A funcao corre antes de qualquer TypeScript existir, pelo que nao pode importar
o `REGRAS` do motor; a lista repete-se, como a gramatica das etiquetas do
`tools/obs_lint` se repete nas tres bibliotecas de metricas. **O que faz a
repeticao valer alguma coisa e a terceira fonte, e e ela que esta aqui:** o
`TestAsDuasListasDeRegras` le as regras do **texto do modulo TypeScript** e
confronta-as com as que estao no `pg_get_functiondef` da funcao **instalada** —
nao com uma copia escrita a mao dentro deste ficheiro, e nao com o literal da
revisao.

A diferenca nao e estilo. Um ensaio com as oito regras escritas a mao prova que
duas copias concordam, e **superficies que concordam nao apanham erro comum**:
quem editasse as duas no mesmo PR tinha-o verde. Lido do `pg_get_functiondef`, o
que se compara e o que a base **tem**, pelo que uma revisao cuja lista literal
difira do que ficou instalado tambem cai aqui.

## E uma coisa que **nao** se prova aqui, e diz-se

O `kamba_batch` tem `BYPASSRLS` (`db/ligacao.py`), pelo que o isolamento desta
escrita **nao vem da RLS**: vem do `p_tenant_id` que o chamador nomeia. E a
mesma condicao da `manual_expirar_confirmacao`, que ja era `EXECUTE` do lote, e
e inerente a um *job* que varre todos os tenants. O que a RLS continua a
garantir e a **leitura** por quem nao e lote, e e isso que o `TestRls` mede.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from tests_pagamentos.base import ComLedger

RAIZ = Path(__file__).resolve().parents[2]

#: O modulo do motor, para o confronto das duas listas de regras.
MOTOR = RAIZ / "packages" / "core-ts" / "src" / "pagamentos" / "anomalias.ts"

#: O nome da porta. **Sem a assinatura**: ela le-se da base, no
#: `TestAsDuasListasDeRegras`, e prende-la aqui era uma quarta copia.
PORTA = "platform.registar_sinal_de_anomalia"

CHAMADA = f"""
  SELECT {PORTA}(
    p_tenant_id => %s, p_regra => %s, p_severidade => %s, p_accao => %s,
    p_contact_id => %s, p_charge_id => %s, p_detalhe => %s::jsonb,
    p_janela => %s::interval)
"""


def _regras_do_motor() -> set[str]:
    """As oito regras, lidas do `REGRAS` do TypeScript.

    Por expressao regular e nao por *parser*: o que se quer e o conjunto dos
    literais da coluna `regra`, e um *parser* de TypeScript aqui era uma
    dependencia nova para ler oito cadeias. Quem o usa afirma `len == 8` antes
    de comparar, pelo que uma leitura que deixasse de casar **nao** passa por
    verde — que e a armadilha desta classe de ensaio.
    """
    texto = MOTOR.read_text(encoding="utf-8")
    bloco = texto[texto.index("export const REGRAS") : texto.index("REGRA_POR_ID")]
    return set(re.findall(r'^\s*regra: "([a-z_]+)",', bloco, re.M))


class ComSinais(ComLedger):
    """Um tenant com cobranca, e as ferramentas para chamar a porta."""

    def registar(
        self,
        cursor,
        tenant: str,
        regra: str = "pagamento_orfao",
        severidade: int = 3,
        accao: str = "registar",
        contacto: str | None = None,
        cobranca: str | None = None,
        detalhe: dict | None = None,
        janela: str = "1 hour",
    ):
        cursor.execute(
            CHAMADA,
            (
                tenant,
                regra,
                severidade,
                accao,
                contacto,
                cobranca,
                json.dumps(detalhe or {}),
                janela,
            ),
        )
        return cursor.fetchone()[0]

    def linhas(self, tenant: str) -> list[tuple]:
        self.semente.execute(
            "SELECT id, regra, severidade, accao, contact_id, charge_id "
            "  FROM platform.fraud_signals WHERE tenant_id = %s ORDER BY id",
            (tenant,),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def corpo_da_porta(self) -> str:
        """O `pg_get_functiondef` da funcao instalada. A terceira fonte."""
        self.semente.execute(
            "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = %s",
            (PORTA.split(".")[1],),
        )
        linhas = self.semente.fetchall()
        self.assertEqual(len(linhas), 1, f"{PORTA} nao esta instalada, ou esta duas vezes")
        return str(linhas[0][0])


class TestAsDuasListasDeRegras(ComSinais):
    def test_as_regras_da_funcao_instalada_sao_as_do_motor(self) -> None:
        """A terceira fonte: o que a base **tem**, contra o texto do motor.

        Ver o cabecalho para a razao de nao haver aqui uma lista escrita a mao.
        """
        motor = _regras_do_motor()
        self.assertEqual(len(motor), 8, motor)
        corpo = self.corpo_da_porta()
        # As regras aparecem no `NOT IN (…)` da guarda, entre apostrofos.
        guarda = re.search(r"NOT IN \(([^)]*)\)", corpo)
        self.assertIsNotNone(guarda, corpo[:400])
        instaladas = set(re.findall(r"'([a-z_]+)'", guarda.group(1)))
        self.assertEqual(motor, instaladas)

    def test_as_duas_regras_do_m3_sao_recusadas_pela_porta(self) -> None:
        """Nao e omissao: e a barreira, e mede-se a correr e nao a ler a lista.

        Quem escreve as duas regras do M-3 e a `manual_confirmar`, que as decide
        **dentro** da transaccao da confirmacao. Deixar um lote forja-las era
        abrir pela porta de servico a decisao que o KAM-054 fechou pela da
        frente.
        """
        tenant = self.criar_tenant()
        lote = self.cursor_papel("batch")
        for regra in ("manual_limite_diario", "manual_limite_por_contacto_24h"):
            with self.assertRaises(Exception) as erro:
                self.registar(lote, tenant, regra=regra, accao="reter_confirmacao")
            self.assertIn("22023", str(erro.exception.args), regra)


class TestPrivilegio(ComSinais):
    def test_o_lote_escreve_e_a_aplicacao_nao(self) -> None:
        """**A propriedade desta revisao, e ela quebra com a mudanca que proibe.**

        A `0032` protegeu de escrever o `kamba_app`, que serve turnos de
        conversa. Esta funcao e `EXECUTE` do `kamba_batch` e **nao** dele, pelo
        que nenhum caminho de conversa ganha forma de escrever no registo que o
        vigia.

        A segunda metade e o que torna isto uma propriedade e nao prosa: se
        alguem acrescentar `GRANT EXECUTE … TO kamba_app`, a chamada deixa de
        levantar `42501` e **este ensaio falha**. Medir so o lado que passa
        deixava a revisao a parecer uma porta quando era um `GRANT INSERT` com
        mais passos.
        """
        tenant = self.criar_tenant()
        lote = self.cursor_papel("batch")
        self.assertIsNotNone(self.registar(lote, tenant))

        app = self.cursor_papel("app", tenant)
        with self.assertRaises(Exception) as erro:
            self.registar(app, tenant)
        self.assertIn("42501", str(erro.exception.args))

    def test_o_execute_nao_se_tornou_um_insert(self) -> None:
        """Depois desta revisao, continua a nao haver `INSERT` para papel nenhum.

        E a afirmacao do `db/tests/test_privilegios.py` que esta revisao nao
        pode contradizer. Mede-se nos **dois** papeis: se um `GRANT INSERT`
        aparecesse por engano num deles, a excepcao estreita virava a larga.
        """
        tenant = self.criar_tenant()
        for identidade in ("app", "batch"):
            cursor = self.cursor_papel(identidade, tenant)
            with self.assertRaises(Exception) as erro:
                cursor.execute(
                    "INSERT INTO platform.fraud_signals "
                    "(tenant_id, regra, severidade, accao) "
                    "VALUES (%s, 'auto_compra', 4, 'reter_confirmacao')",
                    (tenant,),
                )
            self.assertIn("42501", str(erro.exception.args), identidade)


class TestARegraFechaNaFuncao(ComSinais):
    def test_uma_regra_de_fora_da_lista_e_recusada(self) -> None:
        tenant = self.criar_tenant()
        lote = self.cursor_papel("batch")
        with self.assertRaises(Exception) as erro:
            self.registar(lote, tenant, regra="inventada")
        self.assertIn("22023", str(erro.exception.args))

    def test_as_oito_regras_passam(self) -> None:
        """A sonda positiva, e sem ela a de cima ficava verde com a porta fechada.

        Uma funcao que recusasse **tudo** passava o ensaio de recusa com a mesma
        firmeza com que passaria a certa.
        """
        tenant = self.criar_tenant()
        conta = self.criar_conta(tenant)
        lote = self.cursor_papel("batch")
        for regra in sorted(_regras_do_motor()):
            # Uma cobranca por regra: a guarda da janela colapsaria as oito num
            # sinal so se a chave natural fosse a mesma.
            cobranca = self.criar_cobranca(tenant, conta)
            self.assertIsNotNone(
                self.registar(lote, tenant, regra=regra, cobranca=cobranca), regra
            )

    def test_a_coluna_nao_tem_check_e_e_por_isso_que_a_funcao_tem(self) -> None:
        """**O canario da barreira**, e e o que prova que ela mora na funcao.

        Um `INSERT` do superutilizador com uma regra inventada **passa** — a
        coluna e `text NOT NULL` sem `CHECK`, medido. Isto e, a lista fechada
        nao esta na tabela e nao se consegue por la sem alterar o DDL do
        KAM-054. Sem este ensaio, a recusa de cima era indistinguivel de um
        `CHECK` que ja existisse, e esta revisao era arrumacao.
        """
        tenant = self.criar_tenant()
        self.semente.execute(
            "INSERT INTO platform.fraud_signals "
            "(tenant_id, regra, severidade, accao) "
            "VALUES (%s, 'regra_que_nao_existe', 3, 'registar') RETURNING id",
            (tenant,),
        )
        self.assertIsNotNone(self.semente.fetchone()[0])


class TestPii(ComSinais):
    def test_uma_chave_de_pii_no_topo_e_recusada(self) -> None:
        tenant = self.criar_tenant()
        lote = self.cursor_papel("batch")
        with self.assertRaises(Exception) as erro:
            self.registar(lote, tenant, detalhe={"telefone": "o que for"})
        self.assertIn("22023", str(erro.exception.args))

    def test_uma_chave_de_pii_aninhada_tambem(self) -> None:
        """**O caso que a primeira versao da funcao deixava passar.**

        O `jsonb_each_text` le **so o topo**, e um `{"interno": {"telefone": …}}`
        passava-o — com o comentario da funcao a dizer «todos os niveis», que e
        canon a mentir sobre o codigo ao lado. O `jsonb_path_query` com `$.**`
        desce a arvore inteira.

        **E o `detalhe` do motor e plano por tipo** (o `Sinal.detalhe` e
        `Record<string, string | number | boolean | null>`), pelo que este caso
        nao vem de la: vem de quem chamar a porta por outro caminho, que e
        exactamente quem uma barreira na base existe para apanhar.
        """
        tenant = self.criar_tenant()
        lote = self.cursor_papel("batch")
        with self.assertRaises(Exception) as erro:
            self.registar(lote, tenant, detalhe={"interno": {"telefone": "x"}})
        self.assertIn("22023", str(erro.exception.args))

    def test_uma_chave_que_contem_a_palavra_proibida_e_recusada(self) -> None:
        tenant = self.criar_tenant()
        lote = self.cursor_papel("batch")
        with self.assertRaises(Exception) as erro:
            self.registar(lote, tenant, detalhe={"telefone_do_pagador": "x"})
        self.assertIn("22023", str(erro.exception.args))

    def test_o_detalhe_que_o_motor_produz_passa(self) -> None:
        """A sonda positiva: a guarda nao pode recusar o que o motor escreve.

        Os campos sao os do `_sinal` do motor — `account_id`, `ocorrencias`,
        `janela_horas`, `limiar`, `regra_id`, `versao` —, e nenhum deles e PII.
        Sem este par, uma guarda que recusasse tudo passava os tres de cima.
        """
        tenant = self.criar_tenant()
        lote = self.cursor_papel("batch")
        self.assertIsNotNone(
            self.registar(
                lote,
                tenant,
                detalhe={
                    "account_id": str(uuid.uuid4()),
                    "ocorrencias": 3,
                    "janela_horas": 1,
                    "limiar": 3,
                    "regra_id": "R-01",
                    "versao": 1,
                },
            )
        )


class TestJanela(ComSinais):
    def test_o_mesmo_sinal_duas_vezes_da_uma_linha(self) -> None:
        """Sem isto, o *job* periodico escrevia a mesma anomalia por corrida.

        Um registo de vigilancia com mil copias do mesmo facto e um registo que
        ninguem le.
        """
        tenant = self.criar_tenant()
        lote = self.cursor_papel("batch")
        primeiro = self.registar(lote, tenant)
        segundo = self.registar(lote, tenant)
        self.assertEqual(primeiro, segundo)
        self.assertEqual(len(self.linhas(tenant)), 1)

    def test_a_janela_a_zero_escreve_outra_vez(self) -> None:
        """O par: a guarda e da **janela** e nao «um sinal por regra para sempre».

        Com `p_janela => interval '0'`, nenhum sinal anterior cai dentro dela e
        a linha nova escreve-se. Sem este ensaio, uma guarda que ignorasse a
        janela e deduplicasse para sempre passava o de cima — e entao uma
        anomalia que voltasse a acontecer tres meses depois ficava invisivel.
        """
        tenant = self.criar_tenant()
        lote = self.cursor_papel("batch")
        primeiro = self.registar(lote, tenant)
        segundo = self.registar(lote, tenant, janela="0")
        self.assertNotEqual(primeiro, segundo)
        self.assertEqual(len(self.linhas(tenant)), 2)

    def test_dois_sinais_sem_cobranca_e_sem_contacto_nao_se_confundem(self) -> None:
        """**`IS NOT DISTINCT FROM` e nao `=`**, e e este ensaio que o prende.

        Um `charge_id = NULL` nunca e verdadeiro. Com `=`, a guarda **nao
        casava** os sinais sem cobranca — a R-02 e a R-06 — e cada corrida do
        *job* escrevia linha nova. Mede-se com duas chamadas iguais, as duas sem
        cobranca e sem contacto: tem de dar uma linha.
        """
        tenant = self.criar_tenant()
        lote = self.cursor_papel("batch")
        self.registar(lote, tenant, regra="hmac_invalido_em_massa", severidade=4)
        self.registar(lote, tenant, regra="hmac_invalido_em_massa", severidade=4)
        self.assertEqual(len(self.linhas(tenant)), 1)

    def test_regras_diferentes_nao_se_colapsam(self) -> None:
        tenant = self.criar_tenant()
        lote = self.cursor_papel("batch")
        self.registar(lote, tenant, regra="pagamento_orfao")
        self.registar(
            lote, tenant, regra="auto_compra", severidade=4,
            accao="reter_confirmacao",
        )
        self.assertEqual(len(self.linhas(tenant)), 2)

    def test_tenants_diferentes_nao_se_colapsam(self) -> None:
        a, b = self.criar_tenant(), self.criar_tenant()
        lote = self.cursor_papel("batch")
        self.registar(lote, a)
        self.registar(lote, b)
        self.assertEqual(len(self.linhas(a)), 1)
        self.assertEqual(len(self.linhas(b)), 1)


class TestRls(ComSinais):
    def test_o_sinal_de_a_e_invisivel_no_contexto_de_b(self) -> None:
        """A prova de que o `DEFINER` **nao** contorna o `FORCE`.

        E a mesma propriedade que o KAM-054 mediu para as funcoes dele, e
        mede-se outra vez porque e uma funcao nova: a escrita corre como o dono
        e a **leitura** da aplicacao continua sujeita a politica do tenant.
        """
        a, b = self.criar_tenant(), self.criar_tenant()
        self.registar(self.cursor_papel("batch"), a)

        de_a = self.cursor_papel("app", a)
        de_a.execute("SELECT count(*) FROM platform.fraud_signals")
        self.assertEqual(int(de_a.fetchone()[0]), 1)

        de_b = self.cursor_papel("app", b)
        de_b.execute("SELECT count(*) FROM platform.fraud_signals")
        self.assertEqual(int(de_b.fetchone()[0]), 0)


class TestOIndice(ComSinais):
    def test_o_indice_da_janela_existe_e_o_do_painel_fica(self) -> None:
        """Ao `pg_indexes`, e com o controlo positivo na mesma consulta.

        O `fraud_signals_tenant_idx` da `0032` **tem** de ficar: ele serve o
        painel, e uma consulta cega que so procurasse o novo lia-se como «o
        `downgrade` funcionou».
        """
        self.semente.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            " WHERE schemaname = 'platform' AND tablename = 'fraud_signals' "
            " ORDER BY indexname"
        )
        por_nome = {n: d for n, d in self.semente.fetchall()}
        self.assertIn("fraud_signals_tenant_idx", por_nome)
        self.assertIn("fraud_signals_regra_idx", por_nome)
        self.assertRegex(
            por_nome["fraud_signals_regra_idx"], r"\(tenant_id, regra, criado_at\)"
        )


class TestAPortaEstaNaAllowlist(ComSinais):
    def test_a_assinatura_instalada_e_a_que_o_gate_6_aprovou(self) -> None:
        """O `ci/secdef_allowlist.yaml` e fechado **nos dois sentidos**.

        O X-05 do *gate* 6 (`db/tests_isolamento/catalogo.py`) falha com «e
        SECURITY DEFINER e nao esta na lista» **e** com «esta na lista e nao
        existe». A comparacao dele e textual sobre o
        `pg_get_function_identity_arguments`, que inclui os **nomes** dos
        parametros — a forma so-tipos deu seis falhas no KAM-053, e esta no
        comentario daquele ficheiro.

        Este ensaio mede o par aqui, onde o erro aparece ao lado da causa, em
        vez de no *gate* 6 com a mensagem a falar de uma lista.
        """
        self.semente.execute(
            "SELECT 'platform.' || p.proname || '(' "
            "    || pg_get_function_identity_arguments(p.oid) || ')', p.prosecdef "
            "  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = %s",
            (PORTA.split(".")[1],),
        )
        assinatura, secdef = self.semente.fetchone()
        self.assertTrue(secdef, "a porta tem de ser SECURITY DEFINER")
        texto = (RAIZ / "ci" / "secdef_allowlist.yaml").read_text(encoding="utf-8")
        self.assertIn(assinatura, texto, assinatura)
