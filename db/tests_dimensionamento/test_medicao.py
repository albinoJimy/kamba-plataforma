"""A medicao do KAM-084 e o gerador, sem base nem fila.

O que se prova aqui e a **definicao** dos numeros que o relatorio cita — que o
*working set* nao e o reservado nem o `memory.current` com a *page cache*, que
o p99,9 e um valor observado, que a reconciliacao apanha uma repetida — e a
forma do plano de carga. Correm na mesma suite dos cenarios porque partilham o
pacote; nao precisam de nada do gate.
"""

from __future__ import annotations

import json
import unittest

from tests_dimensionamento import gerador, medicao

#: Uma amostra real de cgroup v2, copiada da forma do kernel (valores do ensaio).
CGROUP = """\
157286400
anon 94371840
file 62914560
kernel 2097152
active_file 20971520
inactive_file 41943040
pgfault 1000
usage_usec 12000000
user_usec 9000000
system_usec 3000000
nr_periods 0
"""


class TestWorkingSet(unittest.TestCase):
    def test_e_o_current_menos_a_cache_inactiva(self) -> None:
        leitura = medicao.ler_cgroup(CGROUP, 1.0)
        self.assertEqual(leitura.memory_current, 157_286_400)
        self.assertEqual(leitura.inactive_file, 41_943_040)
        # 150 MiB carregados, 40 MiB de page cache que o kernel larga: 110 MiB.
        self.assertEqual(leitura.working_set, 115_343_360)
        self.assertEqual(leitura.working_set // medicao.MIB, 110)

    def test_nao_e_o_current_nem_o_anon(self) -> None:
        # Os dois erros possiveis: usar o `memory.current` (conta a cache) ou o
        # `anon` (esquece a cache activa, que o servico esta a usar).
        leitura = medicao.ler_cgroup(CGROUP, 1.0)
        self.assertNotEqual(leitura.working_set, leitura.memory_current)
        self.assertNotEqual(leitura.working_set, 94_371_840)

    def test_nunca_negativo(self) -> None:
        self.assertEqual(medicao.working_set(10, 20), 0)

    def test_sem_cgroup_v2_levanta(self) -> None:
        with self.assertRaises(medicao.CgroupIlegivel):
            medicao.ler_cgroup("157286400\nanon 1\n", 1.0)
        with self.assertRaises(medicao.CgroupIlegivel):
            medicao.ler_cgroup("max\n", 1.0)

    def test_o_instante_e_o_uptime_da_vm(self) -> None:
        # O divisor da CPU e o relogio da VM no momento do `cat`, e nao o de
        # quem chamou o `docker exec`: um `exec` lento deslocava o divisor.
        instante, resto = medicao.separar_uptime("812.47 6400.10\n" + CGROUP)
        self.assertEqual(instante, 812.47)
        leitura = medicao.ler_cgroup(resto, instante, local=3.0)
        self.assertEqual((leitura.instante, leitura.local), (812.47, 3.0))
        self.assertEqual(leitura.working_set, 115_343_360)

    def test_sem_uptime_levanta(self) -> None:
        with self.assertRaises(medicao.CgroupIlegivel):
            medicao.separar_uptime(CGROUP.replace("157286400\n", "", 1).replace("anon", "x y", 1))

    def test_a_janela_de_um_degrau_filtra_pelo_relogio_local(self) -> None:
        serie = medicao.Serie(
            [medicao.Leitura(float(t), 0, 0, t * 1_000_000, local=float(t)) for t in range(10)]
        )
        self.assertEqual(len(serie.entre(2.0, 5.0).leituras), 4)

    def test_nucleos_sao_microssegundos_sobre_o_intervalo(self) -> None:
        antes = medicao.Leitura(10.0, 0, 0, 1_000_000)
        depois = medicao.Leitura(12.0, 0, 0, 4_000_000)
        # 3 s de CPU em 2 s de relogio: 1,5 nucleos.
        self.assertAlmostEqual(medicao.nucleos(antes, depois), 1.5)


PROC = """\
cpu  1000 0 500 8000 500 0 0 0 0 0
cpu0 500 0 250 4000 250 0 0 0 0 0
intr 12345
MemTotal:        8000000 kB
MemFree:         1000000 kB
MemAvailable:    6000000 kB
"""


class TestAnfitriao(unittest.TestCase):
    def test_ocupado_e_tudo_menos_idle_e_iowait(self) -> None:
        leitura = medicao.ler_anfitriao(PROC, 1.0)
        self.assertEqual(leitura.total, 10_000)
        self.assertEqual(leitura.ocupado, 1_500)
        # Usada e Total - Available, e nao Total - Free: a cache conta como livre.
        self.assertAlmostEqual(leitura.memoria_usada_mib, 2_000_000 / 1024)

    def test_utilizacao_entre_duas_leituras(self) -> None:
        antes = medicao.LeituraDoAnfitriao(0.0, 1_000, 10_000, 1, 1)
        depois = medicao.LeituraDoAnfitriao(2.0, 1_600, 11_000, 1, 1)
        self.assertAlmostEqual(medicao.utilizacao(antes, depois), 0.6)

    def test_sem_linha_cpu_levanta(self) -> None:
        with self.assertRaises(medicao.CgroupIlegivel):
            medicao.ler_anfitriao("MemTotal: 1 kB\nMemAvailable: 1 kB\n", 1.0)


class TestLimitesDoCompose(unittest.TestCase):
    """Os limites que o ensaio aplica sao os do compose de producao, lidos dele."""

    def test_os_quatro_servicos_medidos(self) -> None:
        from tests_dimensionamento.test_cenarios import COMPOSE_DE_PRODUCAO, limites_do_compose

        texto = COMPOSE_DE_PRODUCAO.read_text(encoding="utf-8")
        self.assertEqual(limites_do_compose(texto, "gwy"), ("256m", "1.0"))
        self.assertEqual(limites_do_compose(texto, "worker-canal"), ("256m", "0.5"))
        self.assertEqual(limites_do_compose(texto, "postgres"), ("5120m", "2.0"))
        self.assertEqual(limites_do_compose(texto, "queue"), ("768m", "1.0"))

    def test_o_bloco_e_o_do_servico_e_nao_o_seguinte(self) -> None:
        from tests_dimensionamento.test_cenarios import limites_do_compose

        texto = "services:\n  a:\n    image: x\n  b:\n    mem_limit: 1m\n    cpus: 2.0\n"
        with self.assertRaises(AssertionError):
            limites_do_compose(texto, "a")
        self.assertEqual(limites_do_compose(texto, "b"), ("1m", "2.0"))


class TestPercentil(unittest.TestCase):
    def test_e_um_valor_observado(self) -> None:
        valores = [float(v) for v in range(1, 1001)]
        self.assertEqual(medicao.percentil(valores, 99.9), 999.0)
        self.assertEqual(medicao.percentil(valores, 50), 500.0)
        self.assertEqual(medicao.percentil(valores, 100), 1000.0)

    def test_a_posicao_arredonda_para_cima(self) -> None:
        # Com 999 amostras o p99,9 e a pior: ceil(0,999 x 999) = 999.
        valores = [float(v) for v in range(1, 1000)]
        self.assertEqual(medicao.percentil(valores, 99.9), 999.0)

    def test_fraccao_abaixo_e_estrita(self) -> None:
        self.assertEqual(medicao.fraccao_abaixo([499.0, 500.0, 501.0, 10.0], 500.0), 0.5)


class TestReconciliacao(unittest.TestCase):
    def test_sem_perdas(self) -> None:
        r = medicao.reconciliar({"a", "b"}, ["b", "a"])
        self.assertEqual((r.em_falta, r.a_mais), (0, 0))

    def test_uma_perdida(self) -> None:
        self.assertEqual(medicao.reconciliar({"a", "b"}, ["a"]).em_falta, 1)

    def test_uma_repetida_conta_como_a_mais(self) -> None:
        # E o que a contagem de conjuntos nao via: as mesmas chaves, duas vezes.
        r = medicao.reconciliar({"a", "b"}, ["a", "b", "b"])
        self.assertEqual(r.em_falta, 0)
        self.assertEqual(r.a_mais, 1)

    def test_uma_estranha_conta_como_a_mais(self) -> None:
        self.assertEqual(medicao.reconciliar({"a"}, ["a", "z"]).a_mais, 1)


class TestPlano(unittest.TestCase):
    def setUp(self) -> None:
        self.canais = [gerador.Canal(f"t{i}", f"w{i}", f"p{i}", i) for i in range(3)]
        self.fabrica = gerador.Fabrica("ensaio-x", self.canais, 5, semente=1)

    def test_taxa_e_duracao(self) -> None:
        plano = self.fabrica.plano(10.0, 4.0)
        self.assertEqual(len(plano), 40)
        self.assertAlmostEqual(plano[1].alvo - plano[0].alvo, 0.1)
        self.assertAlmostEqual(plano[-1].alvo, 3.9)

    def test_um_para_tres(self) -> None:
        plano = self.fabrica.plano(10.0, 4.0)
        kinds = [p.chave[0] for p in plano]
        self.assertEqual(kinds.count("message"), 10)
        self.assertEqual(kinds.count("statuses"), 30)

    def test_chaves_unicas_e_na_forma_do_explosao_ts(self) -> None:
        plano = self.fabrica.plano(10.0, 4.0)
        self.assertEqual(len({p.chave for p in plano}), len(plano))
        for pedido in plano:
            corpo = json.loads(pedido.corpo)
            valor = corpo["entry"][0]["changes"][0]["value"]
            if pedido.chave[0] == "message":
                self.assertEqual(pedido.chave[1], valor["messages"][0]["id"])
            else:
                estado = valor["statuses"][0]
                self.assertEqual(pedido.chave[1], f"{estado['id']}:{estado['status']}")

    def test_a_assinatura_e_sobre_os_bytes(self) -> None:
        pedido = self.fabrica.plano(1.0, 1.0)[0]
        self.assertEqual(pedido.assinatura, gerador.assinar(pedido.corpo, "ensaio-x"))

    def test_telefone_sem_pais(self) -> None:
        self.assertEqual(self.canais[2].telefone(7), "999002000007")
        self.assertTrue(self.canais[2].telefone(7).startswith("999"))

    def test_o_paralelismo_acompanha_a_taxa(self) -> None:
        # A 5/s, 8 ligacoes ficam paradas 1,6 s cada: abaixo dos 5 s do
        # keep-alive do Node, que era o que a primeira corrida do S1 pagava.
        self.assertEqual(gerador.paralelismo_para(5.0), 8)
        self.assertLess(gerador.paralelismo_para(5.0) / 5.0, 5.0)
        self.assertEqual(gerador.paralelismo_para(400.0), 50)
        self.assertEqual(gerador.paralelismo_para(5000.0), 64)

    def test_cada_pedido_leva_o_tenant_do_canal(self) -> None:
        tenants = {c.tenant_id for c in self.canais}
        self.assertTrue(all(p.tenant_id in tenants for p in self.fabrica.plano(10.0, 2.0)))

    def test_o_job_do_agr_e_o_do_chr(self) -> None:
        # `jobIdDe` de `packages/core-ts/src/chr/invocacao.ts`. O valor esperado
        # foi calculado **pelo Node** (`createHash("sha256").update("t1:wamid.X")`)
        # e escrito aqui por extenso: recalcula-lo com o `hashlib` era a mesma
        # conta dos dois lados.
        self.assertEqual(
            gerador.job_do_agr("t1", "wamid.X"),
            "674bd4729afae4b297f84d323e45a391866ef1eda48d570adf29c9ffde1f8ef2",
        )

    def test_reserializado_e_o_mesmo_json_com_outros_bytes(self) -> None:
        original = self.fabrica.plano(1.0, 1.0)[0]
        outro = gerador.reserializado(original, "ensaio-x")
        self.assertNotEqual(outro.corpo, original.corpo)
        self.assertEqual(json.loads(outro.corpo), json.loads(original.corpo))
        self.assertEqual(outro.assinatura, gerador.assinar(outro.corpo, "ensaio-x"))
        self.assertEqual((outro.chave, outro.tenant_id), (original.chave, original.tenant_id))

    def test_dois_planos_nao_repetem_wamid(self) -> None:
        a = {p.chave for p in self.fabrica.plano(10.0, 2.0)}
        b = {p.chave for p in self.fabrica.plano(10.0, 2.0)}
        self.assertFalse(a & b)


if __name__ == "__main__":
    unittest.main()
