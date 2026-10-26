"""Os acoplamentos do consumidor que nenhum teste de execucao ve (KAM-006).

Ha propriedades que vivem **entre** dois ficheiros e que uma suite de execucao
nao distingue de uma coincidencia. A que paga esta classe de teste:

> O BullMQ so chama o `backoffStrategy` do *worker* se as opcoes do *job*
> disserem `backoff: {type: 'custom'}` — e quem cria o *job* e o **publicador**.
> Com o `exponential` que lá estava, a escada do §6.4 (1 s, 5 s, 30 s, 2 min,
> 10 min) nunca era consultada e o recuo real era 1 s, 2 s, 4 s, 8 s, 16 s: a
> contagem de tentativas do criterio 2 ficava certa e os **intervalos**
> errados. Uma suite de integracao com relogio acelerado nao apanha isto, e uma
> com a escada real custava 756 s por teste.

O padrao e o do `TestParidadeDoGuardaDePii` do KAM-005: le-se o TypeScript
**como texto** e confronta-se. Nao substitui os testes de execucao — diz o que
eles nao podem dizer.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
EVENTOS = RAIZ / "packages" / "core-ts" / "src" / "eventos"
FILAS = EVENTOS / "filas_bullmq.ts"
TRABALHADOR = EVENTOS / "trabalhador_bullmq.ts"
CONSUMO = EVENTOS / "consumo.ts"
DLQ = EVENTOS / "dlq.ts"


class TestOsFicheirosExistem(unittest.TestCase):
    def test_os_tres_ficheiros_estao_la(self) -> None:
        for ficheiro in (FILAS, TRABALHADOR, CONSUMO):
            with self.subTest(ficheiro=ficheiro.name):
                self.assertTrue(ficheiro.is_file(), ficheiro)


class TestEscadaDoConsumidor(unittest.TestCase):
    """O *job* pede a escada e o *worker* da-a. As duas metades, juntas."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.filas = FILAS.read_text(encoding="utf-8")
        cls.trabalhador = TRABALHADOR.read_text(encoding="utf-8")
        cls.consumo = CONSUMO.read_text(encoding="utf-8")

    def test_o_job_pede_a_escada_do_consumidor(self) -> None:
        """`backoff: { type: "custom" }` nas opcoes do `addBulk`."""
        self.assertIn('backoff: { type: "custom" },', self.filas)
        self.assertNotIn('type: "exponential"', self.filas)

    def test_o_trabalhador_da_a_escada_que_o_job_pede(self) -> None:
        self.assertIn("backoffStrategy:", self.trabalhador)
        self.assertIn("atrasoDaTentativaDoConsumidor(", self.trabalhador)

    def test_um_adiar_traz_o_seu_atraso_e_nao_o_degrau(self) -> None:
        """Os 5 s do §6.3 nao se confundem com o degrau da escada.

        Sao duas razoes diferentes para esperar: o `Adiar` e «a pre-condicao
        ainda nao chegou» (5 s, e tenta-se outra vez depressa); o degrau e «isto
        falhou» (e cresce). Um `Adiar` a herdar o degrau esperava dez minutos
        por uma encomenda que ia ser paga a seguir.
        """
        self.assertIn("erro instanceof Adiar", self.trabalhador)
        self.assertIn("erro.atrasoMs", self.trabalhador)

    def test_o_numero_de_tentativas_do_job_e_o_da_escada(self) -> None:
        """`REPETICAO.tentativas` e `1 + ESCADA_DO_CONSUMIDOR.length` sao 6.

        Dois numeros em dois ficheiros, e o criterio 2 so esta satisfeito se
        forem o mesmo: com `attempts` a 3, a DLQ abria a terceira tentativa; com
        `attempts` a 10, abria a sexta e o *job* continuava a ser retentado.
        """
        filas_ts = (EVENTOS / "filas.ts").read_text(encoding="utf-8")
        achado = re.search(r"REPETICAO: Repeticao = \{ tentativas: (\d+),", filas_ts)
        self.assertIsNotNone(achado, "nao se encontrou REPETICAO em filas.ts")
        escada = re.search(
            r"ESCADA_DO_CONSUMIDOR = \[(.*?)\] as const;", self.consumo, re.S
        )
        self.assertIsNotNone(escada, "nao se encontrou a escada em consumo.ts")
        degraus = len(re.findall(r"[0-9_]+", escada.group(1)))
        self.assertEqual(int(achado.group(1)), 1 + degraus)
        self.assertEqual(int(achado.group(1)), 6, "o criterio 2 diz 6 (1 + 5)")


class TestContextoDeTenantPorModulo(unittest.TestCase):
    """Cada modulo poe o **seu** contexto de tenant, e poe-no na transaccao.

    E a classe de acoplamento que esta bateria existe para prender, e as duas
    mutacoes que a pediram sobreviveram a noite de 2026-10-26 pela mesma razao —
    uma **segunda camada** que torna as guardas invisiveis a qualquer suite de
    execucao:

        trabalhador_bullmq.ts:  bd.query(SQL_DEFINIR_TENANT, [tenantId, false])
        consumo.ts:             bd.query(SQL_DEFINIR_TENANT, [envelope.tenant_id, true])
        dlq.ts:                 bd.query(SQL_DEFINIR_TENANT, [tenantId, true])

    O `false` do *worker* e `is_local = false`: o contexto fica na **sessao**, na
    mesma ligacao, e a transaccao de cada modulo herda-o. Arrancar o `set_config`
    **local** de dentro do `consumo.ts` ou do `dlq.ts` nao quebra nada em
    `tests_eventos_consumo` — o `WITH CHECK` da politica passa com o valor de
    sessao, e a suite tem um unico *tenant*, pelo que nao ha com que distinguir
    de onde veio.

    A propriedade nao e «a escrita tem contexto»: e «o modulo **nao depende** do
    contexto da ligacao que lhe calhou». E a de `consumo.ts` tem uma segunda
    metade: o *tenant* e o do **envelope**, lido do arquivo, e nao o
    `tenantDoJob(dados)` que o *worker* usa — um *job* forjado ou obsoleto
    marcava o consumo no *tenant* errado.

    Por isso le-se como texto, aqui, e nao se mede por execucao: e o que esta
    classe de teste existe para dizer — «diz o que eles nao podem dizer».
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.consumo = CONSUMO.read_text(encoding="utf-8")
        cls.dlq = DLQ.read_text(encoding="utf-8")
        cls.trabalhador = TRABALHADOR.read_text(encoding="utf-8")

    def test_a_marca_de_consumo_e_do_tenant_do_envelope(self) -> None:
        self.assertIn(
            "await bd.query(SQL_DEFINIR_TENANT, [envelope.tenant_id, true]);",
            self.consumo,
        )

    def test_a_entrada_da_dlq_leva_o_seu_contexto_de_tenant(self) -> None:
        self.assertIn(
            "await bd.query(SQL_DEFINIR_TENANT, [tenantId, true]);", self.dlq
        )

    def test_o_worker_poe_o_contexto_na_sessao_e_os_modulos_na_transaccao(self) -> None:
        """O canario, e e ele que torna os dois de cima necessarios.

        Se o *worker* passasse a por o contexto **local** (`true`), herdar
        deixava de funcionar e as duas guardas de cima passariam a ter efeito
        observavel numa suite de execucao — e estes testes de texto seriam
        redundancia. E se deixasse de o por, as duas de cima passariam a ser a
        **unica** defesa. Nos dois casos a razao escrita no `docstring` desta
        classe deixa de valer, e e isso que se quer que falhe.
        """
        self.assertIn(
            "await bd.query(SQL_DEFINIR_TENANT, [tenantId, false]);", self.trabalhador
        )


class TestOnceForaDaTransaccao(unittest.TestCase):
    """O `once()` nao pode correr dentro da transacção do consumo.

    O PostgreSQL nao encadeia transaccoes: um `BEGIN` dentro de uma transaccao
    aberta e um aviso e mais nada, e o `COMMIT` seguinte fecha a de fora.
    Chamado de dentro do `consumir()`, o `once()` confirmava a marca de
    `events_consumed` **antes de o efeito existir** — e a re-entrega seguinte
    lia «duplicado», pelo que o efeito nunca mais acontecia, sem entrada na DLQ
    e sem o reconciliador o apanhar.

    Le-se como texto porque a guarda e uma linha que se apaga sem nada ficar
    vermelho: a bateria do `once()` corre com uma base falsa, que nao sabe o
    que e uma transaccao encadeada.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.accoes = (EVENTOS / "accoes.ts").read_text(encoding="utf-8")
        cls.consultas = (EVENTOS / "consultas_consumo.ts").read_text(encoding="utf-8")

    def test_a_guarda_existe_e_corre_antes_de_qualquer_begin(self) -> None:
        self.assertIn("await exigirForaDeTransaccao(bd, chave);", self.accoes)
        guarda = self.accoes.index("await exigirForaDeTransaccao(bd, chave);")
        primeiro_begin = self.accoes.index("await bd.query('BEGIN')")
        self.assertLess(
            guarda, primeiro_begin, "a guarda tem de vir antes do primeiro BEGIN"
        )

    def test_a_consulta_da_guarda_compara_os_dois_instantes(self) -> None:
        """`now()` e o da transaccao; `statement_timestamp()` e o da instrucao."""
        self.assertIn("now() <> statement_timestamp()", self.consultas)


class TestReentradaNaDlq(unittest.TestCase):
    """A unicidade da DLQ e parcial, e o `ON CONFLICT` nomeia o predicado."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.consultas = (EVENTOS / "consultas_consumo.ts").read_text(encoding="utf-8")
        cls.revisao = (
            RAIZ / "db" / "migrations" / "versions" / "0005_consumo_dlq.py"
        ).read_text(encoding="utf-8")

    def test_o_indice_e_unico_e_parcial(self) -> None:
        self.assertIn("CREATE UNIQUE INDEX events_dlq_aberta_uq", self.revisao)
        self.assertIn("WHERE estado = 'aberta'", self.revisao)

    def test_o_on_conflict_nomeia_o_predicado_do_indice(self) -> None:
        """Sem o predicado, o PostgreSQL nao infere o indice parcial e rebenta.

        E com uma unicidade sobre o par inteiro, uma entrada ja resolvida
        engolia a falha seguinte: zero entradas abertas sobre um efeito por
        aplicar, que e um Sev1 a apagar-se a si proprio.
        """
        self.assertIn(
            "ON CONFLICT (consumer, event_id) WHERE estado = 'aberta' DO NOTHING",
            self.consultas,
        )

    def test_quem_consome_nao_ganhou_update_nem_delete_na_dlq(self) -> None:
        """A alternativa ao indice parcial era dar `UPDATE` a `kamba_app`.

        Com ele, quem consome passava a poder **fechar** uma entrada sozinho —
        desfazendo, do lado do codigo, a regra dos dois aprovadores. O que ele
        tem e `INSERT` e o `SELECT` de **uma** coluna, a que o predicado do
        `ON CONFLICT` obriga a avaliar.
        """
        concedidos = set(
            re.findall(
                r"GRANT ([A-Z]+)[^\"]*ON platform\.events_dlq TO kamba_app", self.revisao
            )
        )
        self.assertEqual(
            concedidos,
            {"INSERT", "SELECT"},
            "o conjunto de privilegios de kamba_app na DLQ mudou: ver o comentario",
        )
        self.assertIn(
            "GRANT SELECT (consumer, event_id, estado) ON platform.events_dlq",
            self.revisao,
        )
        for proibido in ("UPDATE", "DELETE", "TRUNCATE"):
            self.assertNotIn(proibido, concedidos)


class TestLigacaoDoWorker(unittest.TestCase):
    """O *worker* espera; o publicador desiste. E tem de ser ao contrario.

    O BullMQ **recusa-se** a criar um `Worker` sobre um cliente com
    `maxRetriesPerRequest` diferente de `null` — «Your redis options
    maxRetriesPerRequest must be null» — e tem razao: um *worker* fica
    bloqueado num `BRPOPLPUSH`, e uma leitura que desiste ao fim de N
    tentativas transforma uma reconexao numa paragem de consumo.

    O publicador quer o oposto, e tambem por boa razao: com a fila em baixo o
    `add` tem de **falhar**, para o outbox recuar e tentar outra vez (KAM-005,
    criterio 4).

    Le-se como texto porque o sintoma e o processo a morrer ao arrancar: a
    suite com fila da dezanove testes vermelhos com a mesma linha no registo, e
    nenhum deles aponta para a causa. Este aponta.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.filas = (EVENTOS / "filas_bullmq.ts").read_text(encoding="utf-8")
        cls.trabalhador = (EVENTOS / "trabalhador_bullmq.ts").read_text(encoding="utf-8")

    def test_o_worker_usa_a_ligacao_que_espera(self) -> None:
        self.assertIn("...LIGACAO_QUE_ESPERA", self.trabalhador)
        self.assertNotIn("LIGACAO_QUE_FALHA_DEPRESSA", self.trabalhador)

    def test_a_ligacao_que_espera_tem_maxRetriesPerRequest_nulo(self) -> None:
        bloco = self.filas[self.filas.index("export const LIGACAO_QUE_ESPERA") :]
        bloco = bloco[: bloco.index("};")]
        self.assertIn("maxRetriesPerRequest: null", bloco)

    def test_a_do_publicador_continua_a_desistir(self) -> None:
        """A correccao do consumidor nao pode desfazer o criterio 4 do KAM-005."""
        bloco = self.filas[self.filas.index("export const LIGACAO_QUE_FALHA_DEPRESSA") :]
        bloco = bloco[: bloco.index("};")]
        self.assertIn("enableOfflineQueue: false", bloco)
        self.assertIn("maxRetriesPerRequest: 1", bloco)


class TestUmaLigacaoPorFila(unittest.TestCase):
    """A ligacao e por fila, e isso nao se ve a correr com uma particao."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.trabalhador = TRABALHADOR.read_text(encoding="utf-8")

    def test_a_opcao_e_uma_fabrica_e_nao_uma_ligacao(self) -> None:
        """`concurrency: 1` limita a fila, nao o processo.

        Dezesseis filas sao dezesseis trabalhos ao mesmo tempo. Com uma ligacao
        partilhada, os `BEGIN` e `COMMIT` de dezesseis transaccoes
        intercalavam-se na mesma sessao — um `COMMIT` de uma fila fechava a
        transaccao de outra, e a marca de consumo de um evento ficava confirmada
        com o efeito de outro. Uma suite que corra um evento de cada vez nunca
        ve isto.
        """
        self.assertIn("readonly ligar: () => Promise<LigacaoDoTrabalhador>", self.trabalhador)
        self.assertNotIn("readonly bd: ClienteSql;", self.trabalhador)

    def test_a_concorrencia_por_fila_e_um(self) -> None:
        self.assertIn("concurrency: 1,", self.trabalhador)


if __name__ == "__main__":
    unittest.main()
