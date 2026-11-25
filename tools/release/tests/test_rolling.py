"""Gate 17: uma replica de cada vez, reversao automatica, e a reconciliacao."""

from __future__ import annotations

import unittest

from release import rolling
from release.tests.apoio import lock_com

ANTERIOR = lock_com(gwy=("a", "build"), worker=("b", "build"), postgres=("e", "terceiros"))
NOVO = lock_com(gwy=("c", "build"), worker=("d", "build"), postgres=("e", "terceiros"))


class _Plataforma:
    """Duplo: duas replicas por servico, um relogio, e a concorrencia medida."""

    def __init__(self, doentes: set[str] = frozenset(), imagens_doentes: set[str] = frozenset()) -> None:
        self.agora = 0.0
        self.doentes = set(doentes)
        self.imagens_doentes = set(imagens_doentes)
        self.imagem: dict[str, str] = {}
        self.fora: set[str] = set()
        self.maximo_fora = 0
        self.custo_de_implantar = 10.0

    # relogio e sono
    def relogio(self) -> float:
        return self.agora

    def dormir(self, segundos: float) -> None:
        self.agora += segundos

    # porta
    def replicas(self, servico: str) -> list[str]:
        return [f"{servico}-1", f"{servico}-2"]

    def esvaziar(self, replica: str) -> None:
        self.fora.add(replica)
        self.maximo_fora = max(self.maximo_fora, len(self.fora))
        self.agora += 5

    def implantar(self, replica: str, imagem: str) -> None:
        # Implantar numa replica que esta a servir e cortar turnos a meio.
        if replica not in self.fora:
            raise AssertionError(f"implantar {replica} sem a esvaziar")
        self.imagem[replica] = imagem
        self.agora += self.custo_de_implantar

    def saudavel(self, replica: str) -> bool:
        self.agora += 1
        if replica in self.doentes:
            return False
        return not any(d in self.imagem.get(replica, "") for d in self.imagens_doentes)

    def retomar(self, replica: str) -> None:
        self.fora.discard(replica)


def _rolar(p: _Plataforma, servicos=("gwy", "worker")) -> rolling.Desfecho:
    return rolling.rolar(NOVO, ANTERIOR, list(servicos), p, p.relogio, p.dormir)


class TestRolling(unittest.TestCase):
    def test_implanta_uma_replica_de_cada_vez(self) -> None:
        p = _Plataforma()
        desfecho = _rolar(p)
        self.assertEqual(desfecho.estado, "implantado")
        self.assertEqual(p.maximo_fora, 1)
        self.assertEqual(p.fora, set())
        self.assertTrue(all(NOVO.servicos[r.split("-")[0]].imagem == i for r, i in p.imagem.items()))

    def test_a_ordem_e_esvaziar_implantar_verificar_retomar(self) -> None:
        registo = _rolar(_Plataforma(), servicos=("gwy",)).registo
        self.assertEqual([l.split()[0] for l in registo],
                         ["esvaziar", "implantar", "retomar", "esvaziar", "implantar", "retomar"])

    def test_servico_que_nao_mudou_nao_e_tocado(self) -> None:
        p = _Plataforma()
        _rolar(p, servicos=("gwy", "postgres"))
        self.assertNotIn("postgres-1", p.imagem)

    def test_release_invalida_e_revertida_sem_intervencao(self) -> None:
        # O `/healthz` falha na imagem nova do worker: o gwy ja tinha mudado.
        p = _Plataforma(imagens_doentes={"d" * 64})
        desfecho = _rolar(p)
        self.assertEqual(desfecho.estado, "revertido")
        self.assertEqual(desfecho.falhou_em, "worker-1")
        for replica, imagem in p.imagem.items():
            self.assertEqual(imagem, ANTERIOR.servicos[replica.split("-")[0]].imagem, replica)
        self.assertEqual(p.fora, set())
        self.assertEqual(p.maximo_fora, 1)
        self.assertTrue(desfecho.dentro_do_prazo_de_reversao)

    def test_a_reversao_mede_o_tempo_e_diz_se_passou_os_cinco_minutos(self) -> None:
        p = _Plataforma(imagens_doentes={"d" * 64})
        p.custo_de_implantar = 120.0  # tres reposicoes de dois minutos
        desfecho = _rolar(p)
        self.assertGreater(desfecho.segundos_de_reversao, rolling.PRAZO_DE_REVERSAO_S)
        self.assertFalse(desfecho.dentro_do_prazo_de_reversao)

    def test_reversao_que_falha_e_humana_e_continua_as_outras(self) -> None:
        # A replica gwy-1 nao fica saudavel nem com a imagem antiga.
        p = _Plataforma(doentes={"gwy-1"})
        desfecho = _rolar(p)
        self.assertEqual(desfecho.estado, "reversao_falhou")
        self.assertIn("reposicao-falhou gwy-1", desfecho.registo)

    def test_servico_novo_nao_tem_para_onde_voltar(self) -> None:
        sem = lock_com(gwy=("a", "build"))
        novo = lock_com(gwy=("a", "build"), novo=("f", "build"))
        p = _Plataforma(doentes={"novo-1"})
        desfecho = rolling.rolar(novo, sem, ["gwy", "novo"], p, p.relogio, p.dormir)
        self.assertEqual(desfecho.estado, "reversao_falhou")
        self.assertIn("sem-anterior novo-1", desfecho.registo)

    def test_servico_fora_do_lock_novo_levanta_antes_de_tocar(self) -> None:
        p = _Plataforma()
        with self.assertRaises(ValueError):
            _rolar(p, servicos=("gwy", "inexistente"))
        self.assertEqual(p.imagem, {})


class TestReconciliacao(unittest.TestCase):
    def setUp(self) -> None:
        self.ids = [f"m{i:04d}" for i in range(rolling.MENSAGENS_ESPERADAS)]
        self.acks = {i: 120.0 for i in self.ids}

    def test_o_ensaio_limpo_e_verde(self) -> None:
        r = rolling.reconciliar(self.ids, list(self.ids), list(self.ids), self.acks)
        self.assertTrue(r.verde, r.resumo())

    def test_uma_perdida_e_vermelho(self) -> None:
        r = rolling.reconciliar(self.ids, self.ids[1:], self.ids[1:], self.acks)
        self.assertEqual(r.perdidas, ("m0000",))
        self.assertFalse(r.verde)

    def test_um_efeito_duplicado_e_vermelho(self) -> None:
        r = rolling.reconciliar(self.ids, self.ids + ["m0007"], self.ids, self.acks)
        self.assertEqual(r.duplicadas, ("m0007",))
        self.assertFalse(r.verde)

    def test_resposta_duplicada_tambem(self) -> None:
        r = rolling.reconciliar(self.ids, self.ids, self.ids + ["m0007"], self.acks)
        self.assertFalse(r.verde)

    def test_processada_sem_resposta_e_vermelho(self) -> None:
        r = rolling.reconciliar(self.ids, self.ids, self.ids[:-1], self.acks)
        self.assertEqual(r.sem_resposta, (self.ids[-1],))
        self.assertFalse(r.verde)

    def test_id_estranho_contamina(self) -> None:
        r = rolling.reconciliar(self.ids, self.ids + ["outro"], self.ids, self.acks)
        self.assertEqual(r.estranhas, ("outro",))
        self.assertFalse(r.verde)

    def test_um_ack_lento_em_1500_passa_e_dois_nao(self) -> None:
        # 99,9% de 1.500 sao 1.498,5: uma lenta deixa 1.499 (99,93%), duas 1.498.
        um = dict(self.acks, m0001=900.0)
        self.assertTrue(rolling.reconciliar(self.ids, self.ids, self.ids, um).verde)
        dois = dict(um, m0002=900.0)
        self.assertFalse(rolling.reconciliar(self.ids, self.ids, self.ids, dois).verde)

    def test_ack_de_500_exactos_nao_e_menor_que_500(self) -> None:
        acks = dict(self.acks, m0001=500.0, m0002=500.0)
        self.assertFalse(rolling.reconciliar(self.ids, self.ids, self.ids, acks).verde)

    def test_ack_em_falta_conta_contra(self) -> None:
        acks = dict(self.acks)
        del acks["m0001"]
        r = rolling.reconciliar(self.ids, self.ids, self.ids, acks)
        self.assertEqual(r.acks_em_falta, 1)
        self.assertFalse(r.verde)

    def test_menos_mensagens_do_que_o_ensaio_pede_nao_e_verde(self) -> None:
        curto = self.ids[:100]
        r = rolling.reconciliar(curto, curto, curto, self.acks)
        self.assertFalse(r.verde)


if __name__ == "__main__":
    unittest.main()
