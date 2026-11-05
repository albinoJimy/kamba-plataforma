"""As duas leituras da porta contra um PostgreSQL a serio (KAM-178).

O `SQL_VISTA` (metodo `getOrder`) e o `SQL_LISTAR` (metodo `listOrders`) nasceram
com o KAM-178 e **nao corriam contra motor nenhum**: o
`test_o_modulo_nao_tem_consulta_que_a_suite_nao_exercite` do `test_outbox.py`
apanhou-o — dezasseis declaradas no modulo contra catorze exercitadas — e tinha
razao duas vezes, porque o caso existe exactamente para isto e porque o
`SQL_LISTAR` tem tres construcoes que merecem o motor:

    estado = COALESCE($2::text, estado)
    contact_id = COALESCE($3::uuid, contact_id)
    (criado_at, id) < (COALESCE($4,'infinity'), COALESCE($5,'ffff…'))

**O `COALESCE` no lado esquerdo de uma igualdade e a parte que nenhuma leitura
prova.** Ele compara a coluna consigo mesma quando o filtro nao vem, e isso tem
uma consequencia que so o motor diz: uma linha com a coluna a `NULL` **nao**
casa, porque `NULL = NULL` e desconhecido. Nas duas colunas em questao isso nao
morde — as duas sao `NOT NULL` na revisao `0030` —, e e precisamente o que esta
suite afirma, para que o dia em que alguma deixar de o ser fique vermelho aqui e
nao numa listagem silenciosamente mais curta.

A forma e a do `test_idempotencia.py`: as consultas correm como `kamba_app`, numa
ligacao curta que **confirma**, porque uma transaccao aberta nao ve o que outra
ainda nao confirmou e as leituras desta suite tem de ver o que as sementes
fizeram.
"""

from __future__ import annotations

import uuid

import ligacao
from tests_encomendas.base import ComEncomendas
from tests_encomendas.consultas import SQL_LISTAR, SQL_VISTA

#: Quantas linhas uma pagina traz por omissao no modulo. Ver o `listagem.ts`.
LIMITE_POR_OMISSAO = 20

#: O UUID maximo, que e a posicao de partida do cursor quando nao ha nenhum.
#: Escrito aqui porque e o que o `SQL_LISTAR` escreve como literal, e um ensaio
#: que o adivinhasse media outra consulta.
ID_MAXIMO = "ffffffff-ffff-ffff-ffff-ffffffffffff"


def _ligar_app(tenant: str):
    conexao = ligacao.ligar("app")
    cursor = conexao.cursor()
    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
    cursor.fetchone()
    return conexao, cursor


def _no_app(tenant: str, consulta, *argumentos) -> list[dict]:
    """Corre uma consulta **do modulo** como `kamba_app`, confirma, e fecha.

    A mesma forma do `_no_app` do `test_idempotencia.py`, e pela mesma razao
    escrita la: uma ligacao curta que confirma, para a suite nao bloquear em si
    mesma nem ler uma fotografia.

    **A `consulta` e uma `ConsultaDoTypeScript` e nao uma cadeia**, e os
    argumentos dao-se pela numeracao do documento (`$1`, `$2`, …): o `pg8000`
    nao tem `$n` — tem `%s` e liga-os pela ordem em que aparecem no texto —, e e
    aquela classe que reordena. O `SQL_LISTAR` e o primeiro desta suite onde a
    diferenca morde, porque tem o `$6` do `LIMIT` depois dos quatro filtros.
    (Medido: passar a cadeia directamente da
    `TypeError: 'ConsultaDoTypeScript' object is not iterable`.)

    Devolve dicionarios e nao tuplos, porque estas duas leituras tem nove
    colunas e a asserçao que importa e **o conjunto dos nomes**: por indice, uma
    coluna acrescentada no meio partia todos os casos e nao dizia qual.
    """
    conexao, cursor = _ligar_app(tenant)
    try:
        cursor.execute(consulta.sql, consulta.args(*argumentos))
        colunas = [d[0] for d in (cursor.description or [])]
        linhas = list(cursor.fetchall())
        conexao.commit()
        return [dict(zip(colunas, linha)) for linha in linhas]
    finally:
        conexao.close()


def _cru(tenant: str, sql: str, *argumentos) -> list[dict]:
    """O mesmo, para um SQL que **nao** e do modulo.

    Existe para um caso so — o que compara o literal do cursor com UUID gerados,
    e que tem de ser o **motor** a comparar e nao o Python. Separado do
    `_no_app` de proposito: misturar os dois dava um caminho por onde uma cadeia
    escrita a mao entrava nesta suite a parecer uma consulta do modulo, que e
    exactamente o que o `ConsultaDoTypeScript` existe para impedir.
    """
    conexao, cursor = _ligar_app(tenant)
    try:
        cursor.execute(sql, argumentos)
        colunas = [d[0] for d in (cursor.description or [])]
        linhas = list(cursor.fetchall())
        conexao.commit()
        return [dict(zip(colunas, linha)) for linha in linhas]
    finally:
        conexao.close()


class TestAVistaDaEncomenda(ComEncomendas):
    """O `SQL_VISTA`: o metodo `getOrder` da porta."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.contacto = self.criar_contacto(self.tenant)

    def test_a_vista_devolve_as_nove_colunas_que_a_OrderView_precisa(self) -> None:
        """As nove, por igualdade do conjunto e nao por `assertIn`.

        A `OrderView` do §3.2 monta-se destas colunas, e uma a menos e um campo
        que o adaptador le como `undefined` — que em TypeScript nao rebenta:
        chega ao grafo como `"undefined"` depois do `String()`.
        """
        encomenda = self.criar_encomenda(self.tenant, self.contacto)
        linhas = _no_app(self.tenant, SQL_VISTA, self.tenant, encomenda)
        self.assertEqual(len(linhas), 1)
        self.assertEqual(
            set(linhas[0]),
            {
                "id",
                "numero_publico",
                "estado",
                "version",
                "total_minor",
                "currency",
                "contact_id",
                "lines_snapshot",
                "criado_at",
            },
        )
        self.assertEqual(str(linhas[0]["id"]), encomenda)

    def test_a_vista_nao_ve_a_encomenda_de_outro_tenant(self) -> None:
        """O ISO-01..08 na cadeia, e nao so no adaptador.

        O `$1` e o filtro que o repo-base injecta; aqui mede-se que a **base**
        tambem o aplica — com a RLS atras, que e a segunda barreira.
        """
        outro = self.criar_tenant()
        dele = self.criar_encomenda(outro)
        self.assertEqual(_no_app(self.tenant, SQL_VISTA, self.tenant, dele), [])

    def test_a_vista_nao_ve_uma_encomenda_sob_soft_delete(self) -> None:
        """O `deleted_at IS NULL` esta no predicado e nao no chamador."""
        encomenda = self.criar_encomenda(self.tenant, self.contacto)
        self.semente.execute(
            "UPDATE platform.orders_mirror SET deleted_at = now() "
            " WHERE tenant_id = %s AND id = %s",
            (self.tenant, encomenda),
        )
        self.assertEqual(
            _no_app(self.tenant, SQL_VISTA, self.tenant, encomenda), []
        )


class TestAListagemDeEncomendas(ComEncomendas):
    """O `SQL_LISTAR`: o metodo `listOrders`, com os filtros e o cursor."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.contacto = self.criar_contacto(self.tenant)

    def _listar(self, estado=None, contacto=None, cursor=None, limite=LIMITE_POR_OMISSAO):
        at, ident = cursor if cursor is not None else (None, None)
        return _no_app(
            self.tenant,
            SQL_LISTAR,
            self.tenant,
            estado,
            contacto,
            at,
            ident,
            limite,
        )

    def test_o_coalesce_do_estado_nao_corta_nenhuma_linha(self) -> None:
        """`estado = COALESCE($2::text, estado)` com `$2` nulo devolve tudo.

        **E a construcao que nenhuma leitura prova**: ela compara a coluna
        consigo mesma, e uma coluna anulavel fazia a linha desaparecer porque
        `NULL = NULL` e desconhecido. A `estado` e `NOT NULL` na `0030`, e e
        isso que este caso fixa — o dia em que deixar de ser, fica vermelho aqui.
        """
        self.criar_encomenda(self.tenant, self.contacto)
        self.criar_encomenda(self.tenant, self.contacto)
        self.assertEqual(len(self._listar()), 2)

    def test_o_coalesce_do_contacto_nao_corta_nenhuma_linha(self) -> None:
        """O mesmo para `contact_id = COALESCE($3::uuid, contact_id)`."""
        self.criar_encomenda(self.tenant, self.contacto)
        self.assertEqual(len(self._listar()), 1)

    def test_o_filtro_de_estado_filtra_e_o_de_contacto_tambem(self) -> None:
        """Os dois caminhos legitimos, sem os quais as recusas nao dizem nada."""
        outro_contacto = self.criar_contacto(self.tenant)
        minha = self.criar_encomenda(self.tenant, self.contacto)
        dele = self.criar_encomenda(self.tenant, outro_contacto)
        paga = self.criar_encomenda(self.tenant, self.contacto)
        self.levar_a(self.tenant, paga, "paga")

        por_contacto = {str(l["id"]) for l in self._listar(contacto=self.contacto)}
        self.assertEqual(por_contacto, {minha, paga})
        por_estado = {str(l["id"]) for l in self._listar(estado="criada")}
        self.assertEqual(por_estado, {minha, dele})
        self.assertEqual(
            {str(l["id"]) for l in self._listar(estado="paga")}, {paga}
        )

    def test_a_listagem_nao_ve_as_linhas_de_outro_tenant(self) -> None:
        outro = self.criar_tenant()
        self.criar_encomenda(outro)
        minha = self.criar_encomenda(self.tenant, self.contacto)
        self.assertEqual({str(l["id"]) for l in self._listar()}, {minha})

    def test_o_cursor_de_keyset_desempata_pelo_id_no_mesmo_instante(self) -> None:
        """A razao escrita para o `id` entrar na ordem, medida no motor.

        Duas encomendas com o **mesmo** `criado_at`: com a comparacao so pelo
        instante, a segunda pagina saltava uma ou repetia-a. A comparacao de
        linhas `(criado_at, id) < ($4, $5)` e o que o impede, e e uma construcao
        de PostgreSQL que nenhuma travessia nossa reproduz.
        """
        instante = "2026-11-02T10:00:00+00:00"
        a = self.criar_encomenda(self.tenant, self.contacto, criado_at=instante)
        b = self.criar_encomenda(self.tenant, self.contacto, criado_at=instante)

        primeira = self._listar(limite=1)
        self.assertEqual(len(primeira), 1)
        ultima = primeira[0]

        segunda = self._listar(
            cursor=(str(ultima["criado_at"]), str(ultima["id"])), limite=1
        )
        self.assertEqual(len(segunda), 1, "a segunda linha foi saltada")
        self.assertNotEqual(str(segunda[0]["id"]), str(ultima["id"]))
        self.assertEqual({str(ultima["id"]), str(segunda[0]["id"])}, {a, b})

        # E a terceira pagina esta vazia: as duas sairam e nenhuma repetiu.
        terceira = self._listar(
            cursor=(str(segunda[0]["criado_at"]), str(segunda[0]["id"])), limite=1
        )
        self.assertEqual(terceira, [])

    def test_sem_cursor_a_posicao_de_partida_cobre_todas_as_linhas(self) -> None:
        """O `COALESCE($4,'infinity')` do cursor ausente.

        Nenhuma linha tem `criado_at` infinito, pelo que a comparacao e
        verdadeira para todas — e e assim que a primeira pagina sai inteira sem
        um `OFFSET`. Mede-se com um `criado_at` no futuro, que e o valor que mais
        se aproxima do limite.
        """
        futuro = self.criar_encomenda(
            self.tenant, self.contacto, criado_at="2099-01-01T00:00:00+00:00"
        )
        self.assertIn(futuro, {str(l["id"]) for l in self._listar()})

    def test_o_id_maximo_do_literal_e_maior_do_que_qualquer_uuid_gerado(self) -> None:
        """A outra metade do `COALESCE($5,'ffff…')`, e nao e obvia.

        Se o literal nao fosse o maior UUID possivel, a comparacao de linhas
        cortava a linha mais recente quando o `criado_at` dela empatasse com o
        limite — e isso nunca acontece com `infinity`, mas o par tem de ser
        coerente para que o raciocinio escrito no `SQL_LISTAR` seja verdadeiro.
        Mede-se com a comparacao do proprio motor, e nao com uma em Python.
        """
        gerados = [str(uuid.uuid4()) for _ in range(50)]
        linhas = _cru(
            self.tenant,
            "SELECT count(*) AS acima FROM unnest(%s::uuid[]) AS u(x) "
            " WHERE u.x > %s::uuid",
            gerados,
            ID_MAXIMO,
        )
        self.assertEqual(int(linhas[0]["acima"]), 0)

    def test_a_listagem_respeita_o_limite(self) -> None:
        """O `LIMIT $6` parametrizado, que e o que o modulo usa para pedir N+1."""
        for _ in range(3):
            self.criar_encomenda(self.tenant, self.contacto)
        self.assertEqual(len(self._listar(limite=2)), 2)
        self.assertEqual(len(self._listar(limite=3)), 3)
