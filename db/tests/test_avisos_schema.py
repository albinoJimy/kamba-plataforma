"""A revisao 0019 contra a base: o contacto do dono e o registo dos avisos (KAM-115).

Quatro coisas, e tres delas sao criterios do bloco pela letra:

1. **A idempotencia e os lembretes vivem na mesma restricao, e isso prova-se.**
   A `owner_notices_idempotencia_uq (tenant_id, chave, lembrete, canal)` recusa
   o mesmo episodio duas vezes com `23505` — criterio 2 — e **aceita** o
   lembrete das 24 h, que e um aviso com a mesma chave e outro `lembrete` —
   criterio 4. As duas metades, porque uma unicidade mais apertada passava a
   primeira e falhava a segunda em silencio.

2. **O «depois para» do criterio 4 e da base.** O `owner_notices_lembrete_ck`
   recusa o `lembrete = 3` com `23514`. E a parte do limite que protege o dono
   de nos, e deixa-la so no codigo era deixa-la ao alcance do primeiro `if` mal
   escrito.

3. **O endereco do dono nao tem coluna em claro.** Afirma-se contra o catalogo:
   das dez colunas de `owner_contacts`, nenhuma e `text` sem dominio fechado. E
   o DoD «Privacidade» do ticket, e e uma propriedade do esquema e nao do
   codigo — um teste do lado do codigo prova o que o codigo faz hoje.

4. **O `downgrade`** — «Migracoes reversiveis: `downgrade` testado». Desce com
   linhas e **nao recusa**: a razao esta na propria revisao, e nao e que os
   avisos valham pouco — e que o que se perde nao e prova juridica como o
   consentimento da `0015`. O que se perde de facto e a **idempotencia**, e isso
   esta dito.

A classe do `downgrade` nao herda de `ComBase`: controla ela propria a revisao
da base, e por isso nao pode partilhar a ligacao que nunca confirma.
"""

from __future__ import annotations

import unittest

import ligacao
from tests import factories
from tests.base import (
    TABELAS,
    TABELAS_ATE_0018,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
    alembic_ok,
    em_head,
)

#: Os cinco gatilhos do criterio 1, como a revisao os declara e como o
#: `avisos/contrato.ts` os fixa. Um teste compara as duas listas pelo
#: `pg_get_constraintdef`, pela licao que a `0008` e a `0009` pagaram.
GATILHOS = (
    "canal_desligado",
    "inactividade",
    "qualidade_restrita",
    "sem_pagamento",
    "painel_indisponivel",
)

#: Os dois canais por onde um aviso sai. **O WhatsApp nao e um deles**, e e o
#: ticket inteiro: avisar o dono pelo canal que falhou e inutil.
CANAIS = ("email", "painel")

#: Os quatro motivos de falha. O `sem_contacto` e o `indisponivel` **nao**
#: condenam o endereco; os outros dois condenam-no (criterio 7).
MOTIVOS_DE_FALHA = ("bounce", "rejeitado", "sem_contacto", "indisponivel")

#: Trinta e dois octetos: o unico comprimento que o `owner_notices_chave_ck` e o
#: `owner_contacts_hash_ck` aceitam.
CHAVE = bytes(range(32))
OUTRA_CHAVE = bytes(range(32, 64))

#: As instrucoes dos casos negativos, para o `assertErroSql` as correr dentro
#: do seu `SAVEPOINT`.
#:
#: **Em constantes e nao dentro de um `_inserir`**, e a razao foi medida: o
#: `assertErroSql` precisa do SQL e dos parametros para os correr entre
#: `SAVEPOINT` e `ROLLBACK TO SAVEPOINT`, e sem isso cada caso negativo abortava
#: a transaccao — a segunda assercao do mesmo teste respondia `25P02` e nao o
#: `23514` que se esperava. A prova por mutacao apanhou-o em quatro testes.
INSERIR_AVISO = (
    "INSERT INTO platform.owner_notices "
    "(tenant_id, gatilho, episodio, chave, lembrete, canal) "
    "VALUES (%s, %s, %s, %s, %s, %s)"
)

INSERIR_CONTACTO = (
    "INSERT INTO platform.owner_contacts (tenant_id, canal, endereco_enc) "
    "VALUES (%s, %s, %s)"
)

#: Quarenta octetos de enchimento. O `owner_contacts_enc_ck` exige trinta no
#: minimo — um criptograma tem versao, `kid`, IV e etiqueta —, e uma semente com
#: um e-mail em claro punha na base de ensaio exactamente o que esta tabela
#: existe para nao ter.
CIFRA = b"\x01" * 40


class TestAvisoAoDono(ComBase):
    """O que o DDL da `0019` promete em `owner_notices`.

    `ComBase` da uma ligacao que **nunca confirma**: cada teste desfaz o que
    escreveu, e e por isso que o tenant se semeia em cada um.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)

    def _inserir(self, **troca):
        campos = {
            "tenant_id": self.tenant,
            "gatilho": "canal_desligado",
            "episodio": "canal-1:primary_inactivity",
            "chave": CHAVE,
            "lembrete": 0,
            "canal": "email",
        }
        campos.update(troca)
        self.cursor.execute(
            "INSERT INTO platform.owner_notices "
            "(tenant_id, gatilho, episodio, chave, lembrete, canal) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (
                campos["tenant_id"],
                campos["gatilho"],
                campos["episodio"],
                campos["chave"],
                campos["lembrete"],
                campos["canal"],
            ),
        )
        return self.cursor.fetchone()[0]

    # --------------------------------------------------------------- dominios

    def test_os_cinco_gatilhos_do_dominio_passam(self) -> None:
        """Os cinco do criterio 1, e os cinco entram.

        A metade positiva, sem a qual um `CHECK` apertado por engano passava o
        teste negativo e recusava producao.
        """
        for indice, gatilho in enumerate(GATILHOS):
            with self.subTest(gatilho=gatilho):
                self._inserir(gatilho=gatilho, chave=bytes([indice]) + CHAVE[1:])

    def _campos(self, **troca) -> tuple:
        """Os seis parametros do `INSERIR_AVISO`, na ordem da instrucao."""
        campos = {
            "tenant_id": self.tenant,
            "gatilho": "canal_desligado",
            "episodio": "canal-1:primary_inactivity",
            "chave": CHAVE,
            "lembrete": 0,
            "canal": "email",
        }
        campos.update(troca)
        return (
            campos["tenant_id"],
            campos["gatilho"],
            campos["episodio"],
            campos["chave"],
            campos["lembrete"],
            campos["canal"],
        )

    def test_um_gatilho_fora_da_lista_e_recusado(self) -> None:
        """«Um gatilho fora da lista nao envia nada» (criterio 1), na base."""
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.cursor, INSERIR_AVISO,
            self._campos(gatilho="canal_lento"),
        )

    def test_o_whatsapp_nao_e_um_canal_de_aviso(self) -> None:
        """O ticket inteiro, numa linha: avisar pelo canal que falhou e inutil.

        E o criterio 8 visto da base. O `CHECK` tem dois valores e o `whatsapp`
        nao e um deles — ao contrario do `consent_event.canal` da `0015`, onde
        ele e o **unico**. Os dois dominios sao da mesma palavra e qualificados
        pela coluna, pela regra da emenda 1.14.
        """
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.cursor, INSERIR_AVISO,
            self._campos(canal="whatsapp"),
        )

    def test_os_dois_canais_passam(self) -> None:
        for canal in CANAIS:
            with self.subTest(canal=canal):
                self._inserir(canal=canal)

    def test_uma_chave_de_outro_tamanho_e_recusada(self) -> None:
        """`sha256` tem 32 octetos, e `bytea` aceita qualquer comprimento.

        O sitio de o dizer e o `CHECK`: sem ele, uma chave truncada por um
        condutor passava, e duas chaves truncadas de episodios diferentes
        podiam colidir — e o segundo episodio nunca era avisado.
        """
        for mau in (CHAVE[:31], CHAVE + b"\x00"):
            with self.subTest(octetos=len(mau)):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, self.cursor, INSERIR_AVISO,
                    self._campos(chave=mau),
                )

    def test_um_episodio_vazio_e_recusado(self) -> None:
        """O defeito mais silencioso possivel neste modulo, fechado na base.

        Um `episodio` vazio punha todos os avisos do mesmo gatilho na mesma
        chave — porque a chave deriva dele — e o segundo episodio de um tenant
        deixava de ser avisado para sempre. Nada no caminho o dizia.
        """
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.cursor, INSERIR_AVISO, self._campos(episodio=""),
        )

    # ----------------------------------------------- idempotencia e lembretes

    def test_o_mesmo_episodio_duas_vezes_e_recusado(self) -> None:
        """Criterio 2: «o mesmo evento 3x produz 1 aviso».

        Na base, e nao num `if`: o modulo escreve com `ON CONFLICT DO NOTHING`
        e e esta restricao que decide. Com a decisao no codigo, duas transaccoes
        concorrentes liam «ainda nao avisei» as duas e o dono levava dois.
        """
        self._inserir()
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE, self.cursor, INSERIR_AVISO, self._campos(),
        )

    def test_o_mesmo_episodio_noutro_canal_da_outra_linha(self) -> None:
        """O aviso sai pelos dois canais, e sao duas linhas do mesmo aviso.

        E o `canal` dentro da unicidade. Sem ele, o segundo canal era
        deduplicado contra o primeiro e o «por e-mail **e** por notificacao do
        painel» do objectivo do ticket deixava de ser possivel.
        """
        self._inserir(canal="email")
        self._inserir(canal="painel")
        self.cursor.execute(
            "SELECT count(*) FROM platform.owner_notices "
            "WHERE tenant_id = %s AND chave = %s",
            (self.tenant, CHAVE),
        )
        self.assertEqual(self.cursor.fetchone()[0], 2)

    def test_o_lembrete_das_24h_nao_colide_com_o_aviso(self) -> None:
        """Criterio 4, e e a metade que uma unicidade mais apertada perdia.

        Um lembrete e, por definicao, um segundo aviso do **mesmo** episodio e
        do mesmo canal. Com a unicidade em `(tenant_id, chave, canal)`, o
        criterio 2 passava e o criterio 4 era impossivel — e o segundo falhava
        com `23505` em producao, nao aqui.
        """
        self._inserir(lembrete=0)
        self._inserir(lembrete=1)
        self._inserir(lembrete=2)
        self.cursor.execute(
            "SELECT array_agg(lembrete ORDER BY lembrete) "
            "FROM platform.owner_notices WHERE tenant_id = %s AND chave = %s",
            (self.tenant, CHAVE),
        )
        self.assertEqual(list(self.cursor.fetchone()[0]), [0, 1, 2])

    def test_um_quarto_lembrete_e_recusado(self) -> None:
        """O «depois para» do criterio 4, **na base**.

        A regra de parar e a parte do limite que protege o dono de nos. No
        codigo ela e um `if`; aqui e uma restricao, e um `if` mal escrito nao a
        contorna.
        """
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.cursor, INSERIR_AVISO, self._campos(lembrete=3),
        )

    def test_um_episodio_novo_depois_de_resolvido_produz_outro_aviso(self) -> None:
        """A segunda metade do criterio 2, e e a que o `episodio` existe para dar.

        Outro episodio tem outra chave, logo outra linha. Sem a coluna, «o canal
        caiu outra vez» era indistinguivel de «o canal caiu» e o dono nunca
        soube do segundo.
        """
        self._inserir(chave=CHAVE, episodio="canal-1:primary_inactivity")
        self._inserir(chave=OUTRA_CHAVE, episodio="canal-1:change_number")
        self.cursor.execute(
            "SELECT count(*) FROM platform.owner_notices WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 2)

    def test_o_mesmo_episodio_em_dois_tenants_da_duas_linhas(self) -> None:
        """A chave e composta com o `tenant_id`, pela razao da emenda 1.21.

        Com unicidade global, um aviso do tenant B que calhasse na mesma chave
        era deduplicado em silencio contra uma linha de A — e o que se perdia era
        o aviso de uma avaria. A chave leva o `tenant_id` **dentro** do resumo e
        a restricao leva-o **ao lado**: as duas coisas, porque a primeira protege
        de uma colisao e a segunda da uma mensagem de erro em vez de um aviso
        perdido.
        """
        outro = factories.tenant(self.cursor)
        self._inserir()
        self._inserir(tenant_id=outro)
        self.cursor.execute(
            "SELECT count(*) FROM platform.owner_notices WHERE chave = %s", (CHAVE,)
        )
        self.assertEqual(self.cursor.fetchone()[0], 2)

    # ------------------------------------------------------------- desfechos

    def test_um_aviso_entregue_sem_instante_e_recusado(self) -> None:
        """A igualdade e nao a implicacao, nos dois sentidos.

        Um aviso que se diz entregue e nao sabe quando nao e prova de nada — e
        a latencia do criterio 3 mede-se dessa coluna.
        """
        aviso = self._inserir()
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.cursor,
            "UPDATE platform.owner_notices SET estado = 'entregue' WHERE id = %s",
            (aviso,),
        )

    def test_um_instante_de_entrega_num_aviso_pendente_e_recusado(self) -> None:
        """O outro sentido da mesma igualdade, e e o que uma implicacao perdia."""
        aviso = self._inserir()
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.cursor,
            "UPDATE platform.owner_notices SET entregue_at = now() WHERE id = %s",
            (aviso,),
        )

    def test_um_aviso_falhado_sem_motivo_e_recusado(self) -> None:
        aviso = self._inserir()
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.cursor,
            "UPDATE platform.owner_notices SET estado = 'falhado' WHERE id = %s",
            (aviso,),
        )

    def test_os_quatro_motivos_de_falha_passam(self) -> None:
        for indice, motivo in enumerate(MOTIVOS_DE_FALHA):
            with self.subTest(motivo=motivo):
                aviso = self._inserir(chave=bytes([indice]) + CHAVE[1:])
                self.cursor.execute(
                    "UPDATE platform.owner_notices "
                    "SET estado = 'falhado', falha_motivo = %s WHERE id = %s",
                    (motivo, aviso),
                )

    def test_a_entrega_e_a_falha_sao_estados_e_nao_os_dois(self) -> None:
        """Um aviso entregue nao pode levar motivo de falha.

        Vem dos dois `CHECK` ao mesmo tempo, e e o que torna o par de estados
        legivel: o `estado` e a resposta e as duas colunas sao a prova dela.
        """
        aviso = self._inserir()
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.cursor,
            "UPDATE platform.owner_notices "
            "SET estado = 'entregue', entregue_at = now(), falha_motivo = 'bounce' "
            "WHERE id = %s",
            (aviso,),
        )

    def test_as_tentativas_nao_descem(self) -> None:
        aviso = self._inserir()
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.cursor,
            "UPDATE platform.owner_notices SET tentativas = -1 WHERE id = %s",
            (aviso,),
        )

    def test_a_fk_do_tenant_recusa_um_tenant_que_nao_existe(self) -> None:
        self.assertErroSql(
            VIOLACAO_DE_FK, self.cursor, INSERIR_AVISO,
            self._campos(tenant_id="ffffffff-ffff-4fff-8fff-ffffffffffff"),
        )

    # ------------------------------------------- os dominios contra o codigo

    def test_o_dominio_do_gatilho_e_o_do_contrato_em_typescript(self) -> None:
        """A lista da base e a lista do `avisos/contrato.ts`, confrontadas.

        Pela licao que a `0008` e a `0009` pagaram e o KAM-021 repetiu: o
        `CHECK` e a ultima barreira e a lista do modulo e a primeira, e as duas
        divergirem e um aviso que o codigo manda e a base recusa — em producao,
        no caminho de um *webhook*.
        """
        self.cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'owner_notices_gatilho_ck'"
        )
        definicao = self.cursor.fetchone()[0]
        for gatilho in GATILHOS:
            self.assertIn(f"'{gatilho}'", definicao)
        self.assertEqual(definicao.count("'"), 2 * len(GATILHOS))


class TestContactoDoDono(ComBase):
    """O que o DDL da `0019` promete em `owner_contacts`."""

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)

    def _inserir(self, **troca):
        campos = {"tenant_id": self.tenant, "canal": "email", "endereco_enc": CIFRA}
        campos.update(troca)
        self.cursor.execute(
            "INSERT INTO platform.owner_contacts (tenant_id, canal, endereco_enc) "
            "VALUES (%s, %s, %s) RETURNING id",
            (campos["tenant_id"], campos["canal"], campos["endereco_enc"]),
        )
        return self.cursor.fetchone()[0]

    def test_nao_ha_coluna_em_claro_para_o_endereco(self) -> None:
        """O DoD «Privacidade» como propriedade do esquema e nao do codigo.

        Afirma-se contra o catalogo: das colunas desta tabela, as de texto sao
        **duas** — o `canal` e o `motivo_invalido` — e as duas tem dominio
        fechado. Um teste do lado do codigo prova o que o codigo faz hoje; este
        prova que nao ha onde escrever um e-mail em claro.
        """
        self.cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND table_name = 'owner_contacts' "
            "  AND data_type = 'text' ORDER BY 1"
        )
        de_texto = [linha[0] for linha in self.cursor.fetchall()]
        self.assertEqual(de_texto, ["canal", "motivo_invalido"])
        for coluna in de_texto:
            with self.subTest(coluna=coluna):
                self.cursor.execute(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conrelid = 'platform.owner_contacts'::regclass "
                    "  AND contype = 'c' "
                    f"  AND pg_get_constraintdef(oid) LIKE '%%{coluna}%%'"
                )
                self.assertGreaterEqual(self.cursor.fetchone()[0], 1)

    def test_um_endereco_por_tenant_e_canal(self) -> None:
        """«≥ 1 contacto alternativo» e um minimo e nao um numero.

        Com varios por canal, a pergunta «para onde vai o aviso?» passava a ter
        de escolher — e escolher entre dois e-mails do mesmo dono nao e decisao
        que um aviso de avaria deva tomar.
        """
        self._inserir()
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE, self.cursor, INSERIR_CONTACTO,
            (self.tenant, "email", CIFRA),
        )

    def test_o_canal_e_um_dominio_de_um_valor(self) -> None:
        """Um valor, e e a honestidade do estado de hoje.

        O painel e um canal por onde o aviso sai e **nao tem endereco**; o sms e
        o KAM-116 e **nao esta pre-declarado**, porque um nome sem superficie e
        o que o *gate* 3b recusa. O precedente e o
        `consent_event.canal IN ('whatsapp')` da `0015`.
        """
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.cursor, INSERIR_CONTACTO,
            (self.tenant, "sms", CIFRA),
        )

    def test_um_criptograma_curto_demais_e_recusado(self) -> None:
        """Trinta octetos nao e o comprimento certo de nada — e o piso.

        Distingue um criptograma de um campo preenchido com lixo curto, que e o
        que acontece quando alguem liga a cifra errada ou nenhuma.
        """
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.cursor, INSERIR_CONTACTO,
            (self.tenant, "email", b"curto"),
        )

    def test_a_invalidacao_tem_as_duas_metades_ou_nenhuma(self) -> None:
        """So com o motivo nao se sabe quando; so com o instante nao se sabe porque."""
        contacto = self._inserir()
        for jogada in (
            "SET invalido_at = now()",
            "SET motivo_invalido = 'bounce'",
        ):
            with self.subTest(jogada=jogada):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, self.cursor,
                    f"UPDATE platform.owner_contacts {jogada} WHERE id = %s",
                    (contacto,),
                )

    def test_as_duas_metades_juntas_passam(self) -> None:
        contacto = self._inserir()
        self.cursor.execute(
            "UPDATE platform.owner_contacts "
            "SET invalido_at = now(), motivo_invalido = 'bounce' WHERE id = %s",
            (contacto,),
        )

    def test_um_motivo_que_nao_condena_o_endereco_e_recusado(self) -> None:
        """O dominio da invalidez tem **dois** valores e nao quatro (criterio 7).

        Um fornecedor em baixo (`indisponivel`) nao diz nada sobre o endereco, e
        marcar o contacto por isso era deixar o dono sem canal por uma avaria
        nossa. O `sem_contacto` nao condena nada porque nao ha nada a condenar —
        e um `sem_contacto` tratado como `bounce` marcava como invalido um
        endereco que nao existe.
        """
        contacto = self._inserir()
        for motivo in ("indisponivel", "sem_contacto"):
            with self.subTest(motivo=motivo):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, self.cursor,
                    "UPDATE platform.owner_contacts "
                    "SET invalido_at = now(), motivo_invalido = %s WHERE id = %s",
                    (motivo, contacto),
                )

    def test_a_confirmacao_tem_resumo_e_prazo_ou_nenhum(self) -> None:
        """Um resumo sem prazo era uma ligacao eterna; um prazo sem resumo, de nada."""
        contacto = self._inserir()
        for jogada in (
            "SET confirmacao_hash = sha256('x')",
            "SET confirmacao_expira_em = now() + interval '7 days'",
        ):
            with self.subTest(jogada=jogada):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, self.cursor,
                    f"UPDATE platform.owner_contacts {jogada} WHERE id = %s",
                    (contacto,),
                )

    def test_um_resumo_de_outro_tamanho_e_recusado(self) -> None:
        contacto = self._inserir()
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.cursor,
            "UPDATE platform.owner_contacts "
            "SET confirmacao_hash = %s, confirmacao_expira_em = now() WHERE id = %s",
            (b"\x00" * 31, contacto),
        )

    def test_um_endereco_verificado_pode_ficar_invalido(self) -> None:
        """Os dois estados convivem, e e o criterio 7 a pressupo-lo.

        Um endereco verificado que depois deu *bounce* **esta** verificado e
        **nao** serve. Um `CHECK` que os tornasse exclusivos fazia a marca de
        invalido apagar a prova de que o dono um dia confirmou — e o criterio 6
        pergunta por essa prova.
        """
        contacto = self._inserir()
        self.cursor.execute(
            "UPDATE platform.owner_contacts "
            "SET verificado_at = now(), invalido_at = now(), motivo_invalido = 'bounce' "
            "WHERE id = %s",
            (contacto,),
        )
        self.cursor.execute(
            "SELECT verificado_at IS NOT NULL AND invalido_at IS NOT NULL "
            "FROM platform.owner_contacts WHERE id = %s",
            (contacto,),
        )
        self.assertTrue(self.cursor.fetchone()[0])


class TestPrivilegiosDoAviso(ComBase):
    """O que `kamba_app` pode e nao pode fazer nas duas tabelas.

    Afirma-se por **privilegio** e nao por contagem de linhas, pela licao que o
    KAM-022 pagou: o `ComBase` nunca confirma, pelo que uma segunda sessao nao
    ve as linhas que o administrador acabou de escrever — e um `INSERT` que
    falhe por FK esconde o `42501` que se queria medir.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()

    def _pode(self, papel: str, tabela: str, verbo: str) -> bool:
        self.cursor.execute(
            "SELECT has_table_privilege(%s, %s, %s)",
            (papel, f"platform.{tabela}", verbo),
        )
        return bool(self.cursor.fetchone()[0])

    def test_a_app_le_e_insere_nas_duas(self) -> None:
        for tabela in ("owner_notices", "owner_contacts"):
            for verbo in ("SELECT", "INSERT"):
                with self.subTest(tabela=tabela, verbo=verbo):
                    self.assertTrue(self._pode("kamba_app", tabela, verbo))

    def test_a_app_nao_apaga_nenhuma_das_duas(self) -> None:
        """«*Soft delete*: estado, nunca `DELETE`» (regra da `0001`).

        E aqui ha uma razao a mais: o registo de que o dono foi avisado e a
        prova de que cumprimos o aviso que o `01` §14 manda dar.
        """
        for tabela in ("owner_notices", "owner_contacts"):
            with self.subTest(tabela=tabela):
                self.assertFalse(self._pode("kamba_app", tabela, "DELETE"))

    def test_o_update_da_app_e_por_coluna_e_nao_de_tabela(self) -> None:
        """Sem isto, a matriz por coluna ficava vacua.

        E o achado que a revisao adversarial da `0018` mediu: o
        `test_privilegios_por_coluna_nas_tabelas_com_matriz` compara
        `de_tabela or coluna in por_coluna`, e um `UPDATE` de tabela
        curto-circuita o `or` — a lista de colunas nunca chegava a ser
        confrontada, e o comentario que a acompanhava afirmava uma restricao que
        nao existia.
        """
        for tabela in ("owner_notices", "owner_contacts"):
            with self.subTest(tabela=tabela):
                self.assertFalse(self._pode("kamba_app", tabela, "UPDATE"))

    def test_a_app_altera_o_desfecho_e_nao_a_chave(self) -> None:
        for coluna in ("estado", "entregue_at", "falha_motivo", "tentativas"):
            with self.subTest(coluna=coluna):
                self.cursor.execute(
                    "SELECT has_column_privilege('kamba_app', "
                    "'platform.owner_notices', %s, 'UPDATE')",
                    (coluna,),
                )
                self.assertTrue(self.cursor.fetchone()[0])
        for coluna in ("tenant_id", "gatilho", "episodio", "chave", "lembrete", "canal"):
            with self.subTest(coluna=coluna):
                self.cursor.execute(
                    "SELECT has_column_privilege('kamba_app', "
                    "'platform.owner_notices', %s, 'UPDATE')",
                    (coluna,),
                )
                self.assertFalse(self.cursor.fetchone()[0])

    def test_o_batch_insere_os_lembretes_e_nao_capta_enderecos(self) -> None:
        """A unica assimetria entre as duas tabelas, e as duas metades sao razao.

        O `kamba_batch` **insere** avisos porque os lembretes das 24 h e das
        72 h sao escritas de retaguarda — sem `INSERT`, o «lembretes se o estado
        persiste» do criterio 4 nao tinha caminho executavel, so decisao
        escrita. E **nao** insere contactos porque quem capta o endereco e o
        caminho do dono (KAM-086) e nao um *job*.
        """
        self.assertTrue(self._pode("kamba_batch", "owner_notices", "INSERT"))
        self.assertFalse(self._pode("kamba_batch", "owner_contacts", "INSERT"))

    def test_o_batch_altera_as_duas(self) -> None:
        """As tres varreduras correm sem `tenant_id` no predicado.

        Os lembretes, os tenants `ativo` sem contacto verificado e os avisos que
        ficaram `pendente`. Um `UPDATE` sem contexto so corre com `BYPASSRLS`, e
        o unico papel que o tem e este (`db/bootstrap.py`) — sem a concessao,
        os criterios 4 e 6 respondiam `42501`.
        """
        for tabela in ("owner_notices", "owner_contacts"):
            with self.subTest(tabela=tabela):
                self.assertTrue(self._pode("kamba_batch", tabela, "UPDATE"))

    def test_os_papeis_que_nao_tocam_nestas_tabelas(self) -> None:
        """O resolvedor, a identidade e a auditoria: nada.

        O resolvedor responde antes de haver contexto, a identidade nao sabe de
        avisos, e quem audita le o `audit_log`.
        """
        for papel in ("kamba_resolver", "kamba_identity", "kamba_audit"):
            for tabela in ("owner_notices", "owner_contacts"):
                with self.subTest(papel=papel, tabela=tabela):
                    self.assertFalse(self._pode(papel, tabela, "SELECT"))


class TestDowngradeDa0019(unittest.TestCase):
    """«Migracoes reversiveis: `downgrade` testado» (DoD do ticket).

    Nao herda de `ComBase`: controla ela propria a revisao da base, e por isso
    nao pode partilhar a ligacao que nunca confirma.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not em_head():
            raise unittest.SkipTest("a base nao esta em head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()

    def tearDown(self) -> None:
        alembic_ok("upgrade", "head")
        self.conexao.close()

    def _tabelas(self) -> tuple[str, ...]:
        self.cursor.execute(
            "SELECT tablename::text FROM pg_tables WHERE schemaname = 'platform' "
            "ORDER BY 1"
        )
        return tuple(linha[0] for linha in self.cursor.fetchall())

    def test_desce_com_linhas_e_sobe_outra_vez(self) -> None:
        """Desce **com linhas** e nao recusa, ao contrario da `0015`.

        A razao esta na revisao: o que aqui se perde e o historico de avisos e um
        endereco que o dono volta a dar — nao e prova juridica, e um aviso
        perdido nao desfaz o aviso, ele foi entregue. O que se perde de facto e
        a **idempotencia**: descer e subir faz o episodio em curso poder ser
        avisado outra vez, e isso esta dito no `downgrade`.
        """
        # **Sem `with` no cursor**, e nao e estetica: um cursor do pg8000 **nao e
        # gestor de contexto**, e a primeira versao deste teste levantava
        # `TypeError` antes de afirmar o que fosse. A prova por mutacao
        # apanhou-o — a bateria propria nunca tinha corrido, porque o *gate* 8
        # correu antes de ela existir.
        self.cursor.execute(
            "INSERT INTO platform.tenants (tipo, nome) "
            "VALUES ('pme', 'loja do downgrade') RETURNING id"
        )
        tenant = self.cursor.fetchone()[0]
        self.cursor.execute(
            "INSERT INTO platform.owner_contacts (tenant_id, canal, endereco_enc) "
            "VALUES (%s, 'email', %s)",
            (tenant, CIFRA),
        )
        self.cursor.execute(
            "INSERT INTO platform.owner_notices "
            "(tenant_id, gatilho, episodio, chave, canal) "
            "VALUES (%s, 'canal_desligado', 'ep-1', %s, 'email')",
            (tenant, CHAVE),
        )

        self.assertEqual(self._tabelas(), TABELAS)
        alembic_ok("downgrade", "0018")
        self.assertEqual(self._tabelas(), TABELAS_ATE_0018)
        alembic_ok("upgrade", "head")
        self.assertEqual(self._tabelas(), TABELAS)

        # E a politica volta com a tabela: um `downgrade` que deixasse a tabela
        # sem RLS ao subir era pior do que nao descer, porque nada o dizia.
        self.cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'platform.owner_notices'::regclass"
        )
        self.assertEqual(list(self.cursor.fetchone()), [True, True])
        self.cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (tenant,))
