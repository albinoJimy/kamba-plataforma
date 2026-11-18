"""O processo de lote do onboarding contra o PostgreSQL do gate — KAM-198.

O processo vive em `services/onboarding-web/src/lote/` e o adaptador SQL da fila
em `packages/core-ts/src/revisao/sql.ts`; o ensaio de base de dados e
`packages/core-ts/tests_bd/lote.bd.test.ts`. Esta suite e o que o poe a correr
contra a base descartavel, com o `kamba_batch`, o `kamba_app` e o
administrador, e as migracoes em `head`.

Porque e suite propria: e **TypeScript** contra a base, como a `tests_avisos` e
a `tests_modos`, e nenhuma das baterias de `db/tests/` corre Node. E nao e na
`tests_avisos` porque o objecto e outro — aqui e a fila de revisao da `0048`, o
`onboarding_case` da `0043` e a `screening_decision` da `0044`, e o que se prova
e o processo que os junta.

**O que esta suite nao mede**, e onde se mede: a configuracao, o arranque sem
credenciais, a recusa de um papel trocado, o aviso sem via e as rotas sao do
*gate* 4 (`services/onboarding-web/tests/lote.test.ts`); a forma do trinco e
dos onboardings sobre duplos, tambem (`packages/core-ts/tests/revisao.lote.test.ts`);
o `/metrics` sem fuga e do caso `X-01/ts/lote` do *gate* 6.

**E a lista de espera do KAM-095** (`packages/core-ts/tests_bd/capacidade.bd.test.ts`)
corre aqui tambem: o adaptador SQL dela (`capacidade/sql.ts`) corre como
`kamba_batch` e e no processo de lote que vai ligar (credor KAM-092). E um
ficheiro a mais na mesma suite, e nao uma suite nova: uma suite nova e uma linha
do alvo do *gate* 8 no `Makefile`.

**E a regua de cobranca do KAM-058** (`packages/core-ts/tests_bd/regua.bd.test.ts`),
pela mesma razao: o motor corre como `kamba_batch` e suspende pelo
`transition_tenant` da `0058`, e so a base verdadeira prova a funcao.

**E o off-boarding do KAM-098** (`packages/core-ts/tests_bd/offboarding.bd.test.ts`),
pela mesma razao outra vez: o pedido, o canal e a revogacao correm como
`kamba_batch` e encerram pelo `transition_tenant` da `0058`. A limpeza do
`tenant_state_log` e a do KAM-092, no `after` do ficheiro.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.base import ComBase
from tests_lote import node

FICHEIROS = (
    "tests_bd/lote.bd.test.ts",
    "tests_bd/capacidade.bd.test.ts",
    "tests_bd/regua.bd.test.ts",
    "tests_bd/offboarding.bd.test.ts",
    # KAM-200: o T&S corre no processo de lote (o consumidor, as varreduras e as
    # decisoes da fila), e so a base prova a porta, o registo e os triggers.
    "tests_bd/trust.bd.test.ts",
    # KAM-203: o recalculo da confianca a correr no processo de lote. **Por
    # ultimo**: a volta diaria recalcula todos os tenants da base, e os dos
    # ficheiros de cima ganhariam um nivel 0 a meio dos ensaios deles.
    "tests_bd/confianca.bd.test.ts",
)

#: Os `describe` do ficheiro: os dezanove cenarios do processo de lote partilham as
#: sementes, e a lista de espera (KAM-095) e a regua de cobranca (KAM-058) tem
#: cada uma o seu.
GRUPOS = (
    "o processo de lote contra a base",
    "a lista de espera contra a base",
    "a régua de cobrança contra a base",
    "o off-boarding contra a base",
    "Trust & Safety em produção contra a base",
    "a confiança gradual a correr contra a base",
)

#: Os testes que **tem** de ter corrido e passado, pelo nome. Sao a letra dos
#: criterios do bloco: o ciclo contra a base (2), o efeito por reaplicar e o
#: screening (2), a quota entre processos (5), e a lista que sobrevive, que o
#: servico marca, que um processo nao apaga ao outro e que o lote so ve depois
#: da carencia (2), a fase que a reaplicacao nao desfaz (achado 2 da revisao
#: adversarial), e o processo inteiro a arrancar em `prod` contra a base (1 e 3).
TESTES_OBRIGATORIOS = (
    "uma volta drena a triagem, dá o alerta atrasado uma vez e mede o que a base tem",
    "o efeito por reaplicar aplica a fase, e o aviso sem via deixa-o na lista",
    "o screening de um caso de catálogo grava como kamba_app no tenant do caso, uma vez, e resolve",
    "a quota de uma origem aguenta vinte processos a abrir ao mesmo tempo; sem o trinco, não",
    "a lista de efeitos por reaplicar sobrevive a um reinício do processo",
    "o serviço marca o caso na base antes dos efeitos: uma decisão cujo aviso falha fica marcada",
    "o resolver de um processo não apaga a marca que outro escreveu depois de ele a ler",
    "a carência esconde do lote a marca de quem ainda está a correr os efeitos",
    "reaplicar um pedir_info não desfaz a fase que mudou depois da decisão; sem mudança, aplica-a",
    "o processo arranca em prod com as duas credenciais, serve /healthz e /metrics, e pára no SIGTERM",
    # KAM-092: as duas portas da aprovacao, ligadas. A decisao humana e o
    # `k1_ok` passam a `aprovado` so pelo `advance_case`, com o agregador; e a
    # aprovacao automatica entra na amostra do KAM-089.
    "a decisão humana aprova pela porta: a fase passa a aprovado e sai um tenant.approved, uma vez",
    "com o aceite em falta a decisão sobe como erro, sem ficar na lista, e o varrimento aprova quando o aceite chega",
    "um k1_ok antes do aceite fica por aprovar, e o varrimento aprova e amostra quando ele chega",
    "um k1_ok com um caso de categoria por decidir não aprova, e a aprovação da categoria chega pelo varrimento",
    "o recurso aprovado sai de rejeitado pela porta, e emite uma vez",
    "uma rejeição depois de aprovado e um recurso aprovado não emitem um segundo tenant.approved",
    "o marcarFase não escreve aprovado, nem com o tipo contornado",
    "um k1_ok aprova pela porta e, sem humano, entra na amostra uma vez",
    "um k1_ok com intervenção humana não é amostrado, e com o screening em falta não aprova",
    # KAM-095: o `ListaSql` verdadeiro contra a base (criterio 9, com o
    # controlo sem tranca) e a ordem dos parametros do `transitar`.
    "vinte reservas de casos novos com uma vaga dão uma; sem a tranca do adaptador, mais",
    "convite, expiração e desistência pelo serviço escrevem cada coluna no sítio dela",
    # KAM-058: a regua de cobranca, pelo `correrRegua` verdadeiro como
    # `kamba_batch` sobre o `transition_tenant` da `0058` (criterios 1, 2, 3 e 7).
    "onze dias pelo motor verdadeiro: três passos, uma suspensão com registo e evento, o CHR recusa, e o pagamento repõe",
    "o UNIQUE (billing_cycle_id, passo) recusa um passo repetido escrito à mão pelo lote",
    "o pagamento no D+9 cancela o passo pendente e o tenant não é suspenso",
    "um tenant restrito não é suspenso nem sai do restrito",
    "vinte tenants pagos repõem-se numa volta, e a volta dura menos do que o intervalo",
    # KAM-098: o off-boarding pelo codigo TypeScript, como `kamba_batch` — o
    # pedido com a dupla confirmacao (1, adversarial a), o canal pelo guarda da
    # saga (3), o cancelamento em D3 (adversarial b) e a revogacao com o
    # `tenant.closed` e o crash a meio (5 e 9).
    "o pedido exige as duas confirmações: só com a sessão é recusado e nada se escreve",
    "T&S só encerra um tenant suspenso com uma sanção de encerramento, e o titular não a cancela",
    "um pedido de T&S toma o pedido vivo do titular, que deixa de se poder cancelar",
    "o canal: cancela a subscrição, desliga o canal, e nenhuma chamada toca no WABA nem no número; o CHR deixa de encaminhar",
    "cancelado em D3: o canal volta ao que era, e nenhuma fase seguinte corre",
    "os pendentes: sem encomendas, reservas nem reembolsos abertos, a fase conclui",
    "a revogação no D7: as portas da saga, os entitlements, os canais e um tenant.closed; um crash a meio retoma",
    # KAM-200: o consumidor (1), a escada pela porta com o evento (8 e 9), e as
    # varreduras auditadas com a mudanca de conta (2 e 5).
    "o consumidor como kamba_app: a encomenda do próprio dono dá um auto_compra e o aviso, e a reentrega é duplicada",
    "a escada humana suspende pela porta, com registo e evento, e o recurso provido reactiva",
    "uma volta das varreduras deixa uma linha batch.run por varredura, e a mudança de NIF abre um caso, uma vez, no tenant dela",
    # KAM-203: a volta diaria sobe e desce (1), a sancao chega a base sem
    # esperar pelo dia (4), a aprovacao da o nivel 0 (3), a reentrega do
    # `order.delivered` (2) e o isolamento.
    "a volta diária dá o nível 0, sobe com cinco pedidos elegíveis, a disputa aceite desce, e reexecutar não escreve",
    "uma limitacao da escada automática desce o tenant na varredura seguinte, sem esperar pelo dia",
    "um k1_ok aprova pela porta e o tenant fica no nível 0, como kamba_batch",
    "o order.delivered repetido recalcula duas vezes e escreve uma",
    "o recálculo de A nunca escreve o nível de B: nem o faz nascer, nem o desce",
)


class TestProcessoDeLote(ComBase):
    """Corre o ensaio em Node **uma vez**, e depois olha para o que ficou."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.saida = Path(tempfile.mkdtemp(prefix="kamba-lote-"))
        cls.execucao = node.correr(
            [
                "--test",
                "--test-concurrency=1",
                "--test-reporter=tap",
                "--test-reporter-destination=stdout",
                *FICHEIROS,
            ],
            cls.saida / "lote.tap",
        )
        cls.tap = cls.execucao.stdout
        cls.escrito = cls.execucao.stdout + cls.execucao.stderr

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.saida, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def _falhas_do_tap(cls) -> str:
        linhas = cls.escrito.splitlines()
        partes: list[str] = []
        for indice, linha in enumerate(linhas):
            if re.match(r"^\s*not ok \d+ - ", linha):
                partes.append("\n".join(linhas[indice : indice + 30]))
        resumo = [l for l in linhas if re.match(r"^# (tests|pass|fail) \d+$", l)]
        return "\n\n".join([*partes, " | ".join(resumo)]) or cls.escrito[-4000:]

    def test_o_ensaio_passa(self) -> None:
        self.assertEqual(
            self.execucao.returncode,
            0,
            f"node --test saiu com {self.execucao.returncode}:\n{self._falhas_do_tap()}",
        )

    def test_nenhum_teste_foi_saltado(self) -> None:
        """Num gate, saltar e falhar — a mesma regra do `correr_suite.py`."""
        saltados = re.findall(r"^# skip (\d+)$", self.tap, re.M)
        self.assertEqual([int(n) for n in saltados] or [0], [0], f"TAP:\n{self.tap[-3000:]}")

    def test_o_grupo_correu(self) -> None:
        for grupo in GRUPOS:
            with self.subTest(grupo=grupo):
                self.assertIn(grupo, self.tap)

    def test_os_testes_obrigatorios_passaram(self) -> None:
        """Pelo nome, e com `ok` a frente: a letra do que so a base prova."""
        for nome in TESTES_OBRIGATORIOS:
            with self.subTest(teste=nome):
                self.assertRegex(self.tap, rf"(?m)^\s*ok \d+ - {re.escape(nome)}$")

    def test_a_quota_imprime_a_medicao(self) -> None:
        """O numero do controlo sai no registo: e o que a seccao de verificacao cita."""
        medida = re.search(r"\[KAM-198\] quota (\d+): com trinco (\d+) abertos, sem trinco (\d+)", self.escrito)
        self.assertIsNotNone(medida, self.escrito[-2000:])
        print(f"    {medida.group(0)}")

    def test_a_reserva_da_lista_imprime_a_medicao(self) -> None:
        """O controlo sem tranca do KAM-095: o numero que a seccao de verificacao cita."""
        medida = re.search(r"\[KAM-095\] reserva: com tranca (\d+) concedida\(s\), sem tranca (\d+)", self.escrito)
        self.assertIsNotNone(medida, self.escrito[-2000:])
        print(f"    {medida.group(0)}")

    def test_a_regua_imprime_as_medicoes(self) -> None:
        """O KAM-058: os onze dias contra a base e a volta da reposicao de vinte."""
        for padrao in (
            r"\[KAM-058\] onze dias, cinco voltas por dia, contra a base: \d+ ms",
            r"\[KAM-058\] reposicao: vinte tenants numa volta de \d+ ms \(intervalo \d+ ms\)",
        ):
            with self.subTest(padrao=padrao):
                medida = re.search(padrao, self.escrito)
                self.assertIsNotNone(medida, self.escrito[-2000:])
                print(f"    {medida.group(0)}")


if __name__ == "__main__":
    unittest.main()
