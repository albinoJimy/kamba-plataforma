"""Criterio 1: mil tentativas paralelas sobre stock 10 dao dez reservas e zero acima.

O que so aqui se prova, e nenhum duplo de teste pode: que mil tentativas de
reserva sobre o mesmo SKU deixam **dez** linhas escritas, **zero** acima do
stock, e novecentas e noventa recusas limpas. Um `Promise.all` sobre um objecto
em memoria nao tem transaccoes para serializar; isto tem ligacoes a um
PostgreSQL real a disputar a mesma linha de `platform.offer_terms`.

## Sao **duas** afirmacoes, e cada uma tem a sua barreira

```text
exactamente 10 bem-sucedidas   o predicado aritmetico dentro do proprio UPDATE
0 reservas acima do stock      o CHECK offer_terms_stock_nao_sobrevende_ck
```

E por isso ha **dois** canarios e nao um. O primeiro tira o predicado e deixa o
`CHECK`: as recusas deixam de ser limpas e passam a `23514`, pelo que o ensaio de
cima fica vermelho na asercao «zero erros». O segundo tira os **dois** e mede a
sobrevenda a acontecer de facto — e e esse que impede a leitura errada de que o
«zero» do criterio e verdadeiro por construcao da aritmetica. Nao e: e verdadeiro
porque ha uma restricao.

## O `FOR UPDATE` que nao esta aqui, e porque a sua ausencia e a medicao

Sob `READ COMMITTED` a segunda transaccao espera pela primeira na tranca da linha
e **reavalia** o `WHERE` sobre o valor novo dela. E a medicao que o
`test_concorrencia.py` deste directorio pagou e escreveu para o predicado do
estado — «o predicado do estado, sozinho, serializa» — e vale letra por letra
para a aritmetica do stock.

Logo a mutacao que importa **nao** e «tirar o `FOR UPDATE`», porque nunca houve
nenhum: e separar a leitura da escrita em duas instrucoes, que e o defeito que um
programador escreve naturalmente (`SELECT stock_reservada`, decide em Python,
`UPDATE SET stock_reservada = <o valor lido> + 1`). O `_reservar_lendo_antes`
abaixo e esse defeito, e com o `CHECK` fora ele sobrevende.

## Trinta e duas ligacoes e nao mil, e a escolha nao e minha

O criterio pede «1.000 tentativas paralelas». As tentativas sao **exactamente
1000**; a simultaneidade de pico e **32**, que e a escolha que o
`db/tests_ten/test_concorrencia.py` do KAM-009 ja fez para o mesmo problema —
«1 000 chamadas paralelas de 1 unidade contra limite 100» — e pela mesma razao,
que ele escreve assim:

> **Trinta e duas ligacoes, e nao mil.** Mil ligacoes abertas ao mesmo tempo
> estouram o `max_connections` por omissao (100) e o que se media passava a ser
> a gestao do *pool*.

O `db/gate_bd.py` nao afina o `max_connections`, pelo que a omissao e 100 (tres
reservados ao superutilizador). Seguir o numero do KAM-009 e do
`tests_auditoria_carga` do KAM-012 em vez de escolher outro deixa as tres suites
comparaveis e deixa folga para as ligacoes da propria bateria.

**O que esta suite acrescenta ao padrao e a barreira**, e ela nao e enfeite. O
KAM-009 submete mil tarefas a uma piscina de 32 e conta com o rodar da piscina
para produzir disputa; aqui cada obreiro abre a ligacao, espera num
`threading.Barrier(32)` e so depois tenta. A diferenca e que a simultaneidade
fica **garantida** no instante que decide: sem barreira, a primeira ligacao a
abrir podia reservar as dez antes de a ultima ligar, e o ensaio media mil
tentativas sequenciais com o nome de paralelas — verde, e sobre nada.

A decisao toda acontece nessa primeira vaga (dez escrevem, vinte e duas nao); as
restantes 968 tentativas correm sobre stock esgotado e confirmam que nenhuma
passa depois. Subir a simultaneidade nao torna a propriedade mais verdadeira; o
que a tornaria falsa era uma vaga em que duas passassem com stock para uma, e 32
ja o mede.

**NAO VERIFICADO:** se com simultaneidade de mil o resultado seria outro. Obtem-se
afinando o `max_connections` do contentor do `gate_bd.py`, que e alteracao de
infraestrutura de **todas** as suites e esta fora deste ticket.
"""

from __future__ import annotations

import concurrent.futures
import threading

import ligacao
import pg8000.dbapi
from tests.base import sqlstate
from tests_encomendas.base import ComEncomendas
from tests_encomendas.consultas import SQL_RESERVAR

#: Mil, como o criterio pede. Exactamente mil: o criterio esta em numeros e a
#: skill da fabrica diz que se cumpre a letra («p95 de 20 execucoes» com 17 nao
#: esta cumprido).
TENTATIVAS = 1000

#: O stock do criterio: dez unidades em `garantido`.
STOCK = 10

#: Quantas ligacoes disputam ao mesmo tempo. **Trinta e duas, como o KAM-009 e
#: o KAM-012** — ver a nota do modulo para a razao, que e deles e nao minha.
LIGACOES = 32

#: Quanto cada ligacao tenta. `TENTATIVAS` dividido por `LIGACOES` nao e
#: inteiro, pelo que as primeiras levam uma a mais — e a soma e **exactamente**
#: `TENTATIVAS`, verificada por asercao antes de medir.
POR_LIGACAO = [
    TENTATIVAS // LIGACOES + (1 if i < TENTATIVAS % LIGACOES else 0)
    for i in range(LIGACOES)
]

#: O SQLSTATE de uma violacao de `CHECK`. E o que o canario 1 produz onde o
#: ensaio verdadeiro produz recusa limpa.
VIOLACAO_DE_CHECK = "23514"

#: Os SQLSTATE da revisao `0033`.
VERSAO_NAO_SUBIU = "KA008"
ESTADO_TERMINAL = "KA009"

#: A restricao que impede a sobrevenda. O canario 2 larga-a e repoe-a.
RESTRICAO_DA_SOBREVENDA = "offer_terms_stock_nao_sobrevende_ck"

#: Segundos que a barreira espera antes de desistir. Ver a chamada.
PRAZO_DA_BARREIRA = 120

#: O `SQL_RESERVAR` **sem o predicado aritmetico**. E a mutacao do canario 1, e
#: escreve-se aqui por extenso em vez de se derivar do texto do modulo por
#: substituicao: uma substituicao que falhasse em silencio deixava o canario a
#: correr a consulta certa e a afirmar que a mutacao passa. E a licao que o
#: `SQL_SEM_VERSAO` do `test_concorrencia.py` ja escreveu.
SQL_SEM_PREDICADO = """
  UPDATE platform.offer_terms
     SET stock_reservada = stock_reservada + %s,
         atualizado_at = now()
   WHERE tenant_id = %s AND sku = %s
     AND deleted_at IS NULL
  RETURNING sku, stock_modo, stock_quantidade, stock_reservada
"""


def _reservar_noutra_ligacao(conexao, tenant: str, sku: str, qty: int = 1):
    """Uma tentativa de reserva, na ligacao dada, confirmada ou revertida.

    Devolve `("ok", reservada_depois)`, `("sem_stock", None)` ou
    `("erro", sqlstate)`. **Nao levanta:** o que o ensaio quer e a
    **distribuicao** dos resultados, e uma excepcao a atravessar a piscina
    perdia as outras novecentas e noventa e nove.

    O `("sem_stock", None)` e o caso em que o `UPDATE` casa zero linhas, que e a
    recusa limpa do criterio — e a diferenca face ao `("erro", "23514")` que o
    canario 1 produz e precisamente o que o predicado compra.
    """
    cursor = conexao.cursor()
    try:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        cursor.fetchone()
        cursor.execute(SQL_RESERVAR.sql, SQL_RESERVAR.args(tenant, sku, qty))
        linha = cursor.fetchone()
        if linha is None:
            conexao.rollback()
            return "sem_stock", None
        reservada = int(linha[3])
        conexao.commit()
        return "ok", reservada
    except pg8000.dbapi.DatabaseError as erro:
        conexao.rollback()
        return "erro", sqlstate(erro)


def _reservar_sem_predicado(conexao, tenant: str, sku: str, qty: int = 1):
    """A mutacao do canario 1: o mesmo `UPDATE` sem o predicado aritmetico."""
    cursor = conexao.cursor()
    try:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        cursor.fetchone()
        cursor.execute(SQL_SEM_PREDICADO, (qty, tenant, sku))
        linha = cursor.fetchone()
        if linha is None:
            conexao.rollback()
            return "sem_stock", None
        reservada = int(linha[3])
        conexao.commit()
        return "ok", reservada
    except pg8000.dbapi.DatabaseError as erro:
        conexao.rollback()
        return "erro", sqlstate(erro)


def _reservar_lendo_antes(conexao, tenant: str, sku: str, qty: int = 1):
    """A mutacao do canario 2: le num comando e escreve noutro com o valor lido.

    E o defeito que um programador escreve naturalmente, e o unico que a
    reavaliacao do `WHERE` sob `READ COMMITTED` **nao** salva: o valor decidido
    em Python ja esta velho quando o `UPDATE` o escreve, e escreve-o como
    valor absoluto em vez de incremento.
    """
    cursor = conexao.cursor()
    try:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        cursor.fetchone()
        cursor.execute(
            "SELECT stock_quantidade, stock_reservada FROM platform.offer_terms "
            " WHERE tenant_id = %s AND sku = %s",
            (tenant, sku),
        )
        quantidade, reservada = cursor.fetchone()
        if int(quantidade) - int(reservada) < qty:
            conexao.rollback()
            return "sem_stock", None
        novo = int(reservada) + qty
        cursor.execute(
            "UPDATE platform.offer_terms SET stock_reservada = %s "
            " WHERE tenant_id = %s AND sku = %s",
            (novo, tenant, sku),
        )
        conexao.commit()
        return "ok", novo
    except pg8000.dbapi.DatabaseError as erro:
        conexao.rollback()
        return "erro", sqlstate(erro)


def _em_vagas(tenant: str, sku: str, tentar) -> list[tuple[str, object]]:
    """Corre `TENTATIVAS` tentativas em `LIGACOES` ligacoes, largadas juntas.

    Cada obreiro abre **uma** ligacao, espera na barreira, e so depois tenta a
    sua parte. A barreira e o que faz as 64 chegarem ao `UPDATE` ao mesmo tempo:
    sem ela, a primeira ligacao a abrir reservava sozinha antes de a ultima
    sequer ligar, e o ensaio media mil tentativas **sequenciais** com o nome de
    paralelas — verde, e sobre nada.
    """
    assert sum(POR_LIGACAO) == TENTATIVAS, "a reparticao tem de somar as mil"
    # **Com prazo**, pela razao que o `test_expiracao.py` escreve: um
    # `Barrier.wait()` sem `timeout` espera para sempre, e um obreiro que falhe
    # a abrir a ligacao pendurava os outros trinta e um — a suite **para** em
    # vez de falhar, que e o pior dos dois.
    barreira = threading.Barrier(LIGACOES, timeout=PRAZO_DA_BARREIRA)

    def obreiro(quantas: int) -> list[tuple[str, object]]:
        conexao = ligacao.ligar("app")
        try:
            barreira.wait()
            return [tentar(conexao, tenant, sku) for _ in range(quantas)]
        finally:
            conexao.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=LIGACOES) as piscina:
        tarefas = [piscina.submit(obreiro, q) for q in POR_LIGACAO]
        resultados: list[tuple[str, object]] = []
        for tarefa in concurrent.futures.as_completed(tarefas):
            resultados.extend(tarefa.result())
    return resultados


class ComReservas(ComEncomendas):
    """Um tenant com uma oferta `garantido` de stock conhecido."""

    def criar_oferta(
        self,
        tenant: str,
        sku: str = "arroz-5kg",
        *,
        quantidade: int | None = STOCK,
        modo: str = "garantido",
    ) -> str:
        """Uma linha de `offer_terms` com stock. Semeada e confirmada.

        O `preco_tipo`/`preco_minor` vao como `sob_consulta`/nulo, que e o unico
        par que satisfaz o `offer_terms_preco_ck` sem inventar um numero — a
        mesma escolha da receita `_oferta` de `db/tests_isolamento/sementes.py`.
        """
        self.semente.execute(
            "INSERT INTO platform.offer_terms "
            "       (tenant_id, sku, nome, preco_tipo, stock_modo, "
            "        stock_quantidade, estado) "
            "VALUES (%s, %s, %s, 'sob_consulta', %s, %s, 'publicado')",
            (tenant, sku, f"Produto {sku}", modo, quantidade),
        )
        return sku

    def stock_de(self, tenant: str, sku: str) -> tuple[int | None, int]:
        """O par `(quantidade, reservada)` lido pela semente."""
        self.semente.execute(
            "SELECT stock_quantidade, stock_reservada FROM platform.offer_terms "
            " WHERE tenant_id = %s AND sku = %s",
            (tenant, sku),
        )
        quantidade, reservada = self.semente.fetchone()
        return (None if quantidade is None else int(quantidade)), int(reservada)

    def _limpar(self) -> None:
        for tenant in list(self._tenants):
            self.semente.execute(
                "DELETE FROM platform.stock_reservations WHERE tenant_id = %s",
                (tenant,),
            )
            self.semente.execute(
                "DELETE FROM platform.offer_terms WHERE tenant_id = %s", (tenant,)
            )
        super()._limpar()


class TestReservaSobConcorrencia(ComReservas):
    """Criterio 1: dez vencedoras, novecentas e noventa recusas, zero acima."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.sku = self.criar_oferta(self.tenant)

    def test_mil_paralelas_sobre_stock_dez_dao_dez_reservas_e_zero_acima(self) -> None:
        resultados = _em_vagas(self.tenant, self.sku, _reservar_noutra_ligacao)

        vencedoras = [v for r, v in resultados if r == "ok"]
        recusas = [v for r, v in resultados if r == "sem_stock"]
        erros = [v for r, v in resultados if r == "erro"]

        self.assertEqual(len(resultados), TENTATIVAS, "mil tentativas, a letra")
        self.assertEqual(
            erros,
            [],
            "uma recusa por falta de stock nao e um erro de SQL: o predicado "
            "aritmetico faz o UPDATE casar zero linhas, e e isso que o canario "
            "1 mostra ao desaparecer",
        )
        self.assertEqual(
            len(vencedoras),
            STOCK,
            "o predicado `stock_quantidade - stock_reservada >= $3` deixa "
            "passar exactamente dez",
        )
        self.assertEqual(len(recusas), TENTATIVAS - STOCK)
        self.assertEqual(
            sorted(vencedoras),
            list(range(1, STOCK + 1)),
            "as dez veem o `stock_reservada` a subir de um em um, sem buracos "
            "e sem repeticoes: duas a ler o mesmo valor era a sobrevenda a "
            "comecar",
        )

        quantidade, reservada = self.stock_de(self.tenant, self.sku)
        self.assertEqual((quantidade, reservada), (STOCK, STOCK))
        self.assertLessEqual(
            reservada, quantidade, "**zero** reservas acima do stock, a letra"
        )

    def test_canario_sem_o_predicado_as_recusas_deixam_de_ser_limpas(self) -> None:
        """**Canario 1.** Tira o predicado e deixa o `CHECK`: aparecem erros.

        E a prova de que o ensaio de cima mede o predicado: sem ele, o que
        acontece nao e sobrevenda — e `23514`, porque o `CHECK` da `0033` apanha
        a decima primeira. O numero de vencedoras continua a ser dez, pelo que
        um ensaio que so contasse vencedoras **ficava verde com a barreira
        tirada**, e e precisamente essa a leitura que este canario impede.

        O que muda, e e a asercao «zero erros» do ensaio de cima, e que as
        novecentas e noventa recusas passam de limpas a excepcoes. Uma reserva
        de encomenda com varias linhas abortava a transaccao inteira e levava
        consigo as linhas que **tinham** stock, em vez de devolver
        `OUT_OF_STOCK` para a linha que nao tem.
        """
        resultados = _em_vagas(self.tenant, self.sku, _reservar_sem_predicado)

        vencedoras = [v for r, v in resultados if r == "ok"]
        erros = [v for r, v in resultados if r == "erro"]

        self.assertEqual(
            len(vencedoras),
            STOCK,
            "o CHECK sozinho tambem deixa passar dez — e e por isso que contar "
            "vencedoras nao distingue as duas barreiras",
        )
        self.assertNotEqual(
            erros, [], "sem o predicado, as recusas chegam como erro de SQL"
        )
        self.assertEqual(
            set(erros),
            {VIOLACAO_DE_CHECK},
            "e o erro e a violacao do offer_terms_stock_nao_sobrevende_ck",
        )
        self.assertEqual(len(erros), TENTATIVAS - STOCK)

        quantidade, reservada = self.stock_de(self.tenant, self.sku)
        self.assertEqual(
            (quantidade, reservada),
            (STOCK, STOCK),
            "e o stock continua certo: com o CHECK no sitio, tirar o predicado "
            "nao sobrevende — degrada a recusa",
        )

    def test_canario_sem_predicado_e_sem_check_a_sobrevenda_acontece(self) -> None:
        """**Canario 2.** Tira as duas barreiras e mede a sobrevenda a acontecer.

        Sem este canario, o «zero reservas acima do stock» do criterio podia
        ler-se como verdadeiro por construcao — «a aritmetica nunca deixaria
        passar» —, e nao e: e verdadeiro porque ha uma restricao e um predicado.

        A leitura e separada da escrita (`_reservar_lendo_antes`), que e o
        defeito real: a reavaliacao do `WHERE` sob `READ COMMITTED` salva um
        `UPDATE` que faca a aritmetica **dentro** de si, e nao salva um que
        escreva um valor absoluto decidido antes.

        ## A medicao que corrigiu este ensaio, e fica escrita

        A primeira versao afirmava que o `stock_reservada` ficaria **acima** da
        `stock_quantidade`. **Mediu-se, e nao fica: fica exactamente em 10.** O
        defeito e um *lost update* e nao uma soma a mais — cada transaccao
        escreve um **valor absoluto** lido antes, pelo que a segunda a chegar
        espera na tranca da linha e escreve por cima o seu valor velho, em vez
        de somar ao da primeira. O contador nao inflaciona: **perde escritas**.

        Logo a sobrevenda nao se mede no contador, mede-se nas **promessas**: um
        numero de tentativas superior ao stock recebeu `ok`, isto e, mais de dez
        clientes foram informados de que o stock deles estava reservado. E o
        contador fica **abaixo** do numero de promessas, o que e a segunda
        metade do mesmo defeito e e pior do que um contador alto: nem sequer
        registou o que foi prometido, pelo que nenhuma reconciliacao posterior
        descobriria a diferenca a partir dele.

        As duas asercoes abaixo sao as duas metades, e e por isso que sao duas.

        A restricao e reposta no `finally`, e a base do *gate* e descartavel de
        qualquer forma (`exigir_base_descartavel`).
        """
        self.semente.execute(
            f"ALTER TABLE platform.offer_terms "
            f"DROP CONSTRAINT {RESTRICAO_DA_SOBREVENDA}"
        )
        try:
            resultados = _em_vagas(self.tenant, self.sku, _reservar_lendo_antes)
            vencedoras = [v for r, v in resultados if r == "ok"]
            quantidade, reservada = self.stock_de(self.tenant, self.sku)

            self.assertGreater(
                len(vencedoras),
                STOCK,
                "**a sobrevenda**: sem as duas barreiras, mais do que dez "
                "tentativas recebem `ok` sobre stock dez — mais de dez clientes "
                "informados de que tem stock reservado",
            )
            self.assertLess(
                reservada,
                len(vencedoras),
                "e o contador fica **abaixo** das promessas, por *lost "
                "update*: a escrita absoluta de quem chega depois passa por "
                "cima da de quem chegou antes. E a segunda metade do defeito, "
                "e a pior — o contador nao registou o que foi prometido",
            )
            self.assertLessEqual(
                reservada,
                quantidade,
                "medido, e contra-intuitivo: o contador **nao** passa da "
                "quantidade. Quem procurasse a sobrevenda nele nao a "
                "encontrava, e era essa a leitura errada que este ensaio "
                "existia para evitar e que a primeira versao dele fazia",
            )
        finally:
            self.semente.execute(
                "UPDATE platform.offer_terms SET stock_reservada = 0 "
                " WHERE tenant_id = %s AND sku = %s",
                (self.tenant, self.sku),
            )
            self.semente.execute(
                f"ALTER TABLE platform.offer_terms "
                f"ADD CONSTRAINT {RESTRICAO_DA_SOBREVENDA} "
                f"CHECK (stock_quantidade IS NULL "
                f"       OR stock_reservada <= stock_quantidade)"
            )

    def test_um_garantido_sem_quantidade_e_recusado_na_coluna(self) -> None:
        """O *fail-closed* da `0033`: `garantido` exige quantidade.

        E o que impede o predicado aritmetico de ter de decidir sobre um nulo:
        um `garantido` sem numero nunca chega a ser reservavel, porque nunca
        chega a existir.
        """
        estado = self.tentar(
            "INSERT INTO platform.offer_terms "
            "       (tenant_id, sku, nome, preco_tipo, stock_modo, estado) "
            "VALUES (%s, 'sem-numero', 'Sem numero', 'sob_consulta', "
            "        'garantido', 'rascunho')",
            (self.tenant,),
        )
        self.assertEqual(
            estado,
            VIOLACAO_DE_CHECK,
            "offer_terms_stock_garantido_exige_quantidade_ck: uma promessa de "
            "exclusividade sem numero nao se cumpre",
        )

    def test_dois_tenants_no_mesmo_sku_tem_contagens_independentes(self) -> None:
        """**Criterio 8.** ISO-33..38 e ISO-51..56, contra a base.

        «Colisao de SKU entre tenants e pedidos simultaneos de A e B ao mesmo
        SKU global dao contagens independentes.»

        O que o torna verdadeiro **por construcao** e a chave primaria composta
        `(tenant_id, sku)` da `offer_terms` (revisao `0028`): o mesmo texto de
        `sku` em dois tenants sao **duas linhas**, e o predicado aritmetico
        actua sobre a linha do tenant do contexto. Nao e uma propriedade do
        modulo — e do esquema —, e e por isso que este ensaio a mede em vez de a
        afirmar.

        Os dois reservam **ao mesmo tempo** sobre o mesmo texto de SKU, cada um
        com stock 10, e cada um esgota o **seu**: vinte reservas no total e
        nenhuma a ver o stock do outro.
        """
        outro = self.criar_tenant()
        self.criar_oferta(outro, self.sku)

        def esgotar(tenant: str) -> list[str]:
            conexao = ligacao.ligar("app")
            try:
                return [
                    _reservar_noutra_ligacao(conexao, tenant, self.sku)[0]
                    for _ in range(STOCK + 2)
                ]
            finally:
                conexao.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as piscina:
            meus, dele = (
                piscina.submit(esgotar, self.tenant),
                piscina.submit(esgotar, outro),
            )
            resultados = {"a": meus.result(), "b": dele.result()}

        for quem, lista in resultados.items():
            self.assertEqual(
                lista.count("ok"),
                STOCK,
                f"o tenant {quem} esgotou o SEU stock de dez, nem mais nem menos",
            )
            self.assertEqual(lista.count("sem_stock"), 2)

        self.assertEqual(
            self.stock_de(self.tenant, self.sku),
            (STOCK, STOCK),
            "o contador de A nao viu as reservas de B",
        )
        self.assertEqual(
            self.stock_de(outro, self.sku),
            (STOCK, STOCK),
            "nem o de B as de A: sao duas linhas, e a chave composta e a razao",
        )

    def test_um_indicativo_sem_quantidade_reserva_sem_promessa(self) -> None:
        """O criterio 8: `indicativo` reserva internamente, sem exclusividade.

        O `stock_reservada` sobe — a reserva e **contada** —, e nao e limitada,
        que e precisamente «sem promessa de exclusividade». As mil passam todas,
        e isso nao e um defeito: e a letra do criterio.
        """
        sku = self.criar_oferta(
            self.tenant, "feijao-1kg", quantidade=None, modo="indicativo"
        )
        conexao = ligacao.ligar("app")
        try:
            resultados = [
                _reservar_noutra_ligacao(conexao, self.tenant, sku) for _ in range(20)
            ]
        finally:
            conexao.close()

        self.assertEqual(
            [r for r, _ in resultados],
            ["ok"] * 20,
            "sem quantidade declarada nao ha tecto: o `stock_quantidade IS "
            "NULL` do predicado deixa passar",
        )
        quantidade, reservada = self.stock_de(self.tenant, sku)
        self.assertEqual(
            (quantidade, reservada),
            (None, 20),
            "contadas e nao limitadas, que e o que «sem promessa» significa",
        )
