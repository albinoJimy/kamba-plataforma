"""Nenhuma metrica do AGR leva identificador em etiqueta (OBS-I).

`docs/seguranca/ameacas_stride.md`, `OBS-I`: identificadores em etiquetas
explodem a cardinalidade e re-identificam. A regra impoe-se pela **gramatica** e
nao por uma lista de nomes proibidos — uma lista protegia contra os nomes de que
alguem se lembrou; a gramatica protege contra a forma.
"""

from __future__ import annotations

import re
import unittest
import uuid

from kamba_agr.metricas import (
    DESFECHOS,
    ETIQUETA,
    METRICA_COALESCIDAS,
    METRICA_CONTRAPRESSAO,
    METRICA_DURACAO,
    METRICA_FILA,
    METRICA_RECUSADOS,
    METRICA_TURNOS,
    MOTIVOS_DE_RECUSA,
    EtiquetaInvalida,
    MetricasDoAgr,
)


class TestEtiquetas(unittest.TestCase):
    def setUp(self) -> None:
        self.metricas = MetricasDoAgr()

    def test_um_tenant_id_levanta_pela_gramatica(self) -> None:
        for identificador in (str(uuid.uuid4()), str(uuid.uuid4()).replace("-", "")[:40]):
            with self.subTest(valor=identificador[:8]):
                with self.assertRaises(EtiquetaInvalida):
                    self.metricas.contar(METRICA_TURNOS, identificador)

    def test_a_gramatica_recusa_o_que_um_uuid_e(self) -> None:
        self.assertFalse(ETIQUETA.match(str(uuid.uuid4())))
        self.assertTrue(ETIQUETA.match("executado"))

    def test_so_os_valores_da_lista_fechada_passam(self) -> None:
        for desfecho in DESFECHOS:
            with self.subTest(desfecho=desfecho):
                self.metricas.contar(METRICA_TURNOS, desfecho)
        with self.assertRaises(EtiquetaInvalida):
            self.metricas.contar(METRICA_TURNOS, "desfecho_novo")

    def test_os_motivos_de_recusa_sao_os_tres(self) -> None:
        for motivo in MOTIVOS_DE_RECUSA:
            with self.subTest(motivo=motivo):
                self.metricas.contar(METRICA_RECUSADOS, motivo)
        with self.assertRaises(EtiquetaInvalida):
            self.metricas.contar(METRICA_RECUSADOS, "outro")

    def test_uma_metrica_sem_etiqueta_recusa_etiqueta(self) -> None:
        for metrica in (METRICA_COALESCIDAS, METRICA_CONTRAPRESSAO):
            with self.subTest(metrica=metrica):
                self.metricas.contar(metrica)
                with self.assertRaises(EtiquetaInvalida):
                    self.metricas.contar(metrica, "executado")

    def test_um_contador_desconhecido_recusa(self) -> None:
        with self.assertRaises(EtiquetaInvalida):
            self.metricas.contar("agr_inventada_total", "executado")

    def test_uma_medida_desconhecida_recusa(self) -> None:
        with self.assertRaises(EtiquetaInvalida):
            self.metricas.medir("agr_inventada_ms", 1)
        with self.assertRaises(EtiquetaInvalida):
            # Um contador nao e uma medida, e vice-versa.
            self.metricas.medir(METRICA_TURNOS, 1)


class TestContagem(unittest.TestCase):
    def setUp(self) -> None:
        self.metricas = MetricasDoAgr()

    def test_soma_e_repoe(self) -> None:
        self.metricas.contar(METRICA_TURNOS, "executado", quanto=3)
        self.metricas.contar(METRICA_TURNOS, "executado")
        self.assertEqual(self.metricas.ler()[f"{METRICA_TURNOS}:executado"], 4)
        self.metricas.repor()
        self.assertEqual(self.metricas.ler(), {})

    def test_uma_medida_guarda_o_ultimo_valor_e_nao_a_soma(self) -> None:
        self.metricas.medir(METRICA_DURACAO, 100)
        self.metricas.medir(METRICA_DURACAO, 42)
        self.assertEqual(self.metricas.ler()[METRICA_DURACAO], 42.0)

    def test_a_exposicao_tem_help_type_e_as_series(self) -> None:
        self.metricas.contar(METRICA_TURNOS, "executado", quanto=2)
        self.metricas.contar(METRICA_RECUSADOS, "ritmo")
        self.metricas.medir(METRICA_FILA, 7)
        texto = self.metricas.exposicao()
        self.assertIn(f"# TYPE {METRICA_TURNOS} counter", texto)
        self.assertIn(f'{METRICA_TURNOS}{{outcome="executado"}} 2', texto)
        self.assertIn(f'{METRICA_RECUSADOS}{{motivo="ritmo"}} 1', texto)
        self.assertIn(f"# TYPE {METRICA_FILA} gauge", texto)
        self.assertIn(f"{METRICA_FILA} 7", texto)

    def test_a_exposicao_vazia_e_vazia(self) -> None:
        self.assertEqual(self.metricas.exposicao(), "")

    def test_a_exposicao_nao_tem_identificador_nenhum(self) -> None:
        # O que a gramatica garante, verificado tambem na saida: e a saida que
        # vai para um painel.
        for desfecho in DESFECHOS:
            self.metricas.contar(METRICA_TURNOS, desfecho)
        for motivo in MOTIVOS_DE_RECUSA:
            self.metricas.contar(METRICA_RECUSADOS, motivo)
        self.metricas.medir(METRICA_DURACAO, 12)
        series = [
            linha
            for linha in self.metricas.exposicao().splitlines()
            if not linha.startswith("#")
        ]
        self.assertTrue(series)
        for linha in series:
            nome, _, valor = linha.rpartition(" ")
            with self.subTest(linha=linha):
                self.assertTrue(valor)
                # Nenhum valor de etiqueta tem a forma de um UUID: a gramatica
                # recusa hifenes. (`tecto_do_tenant` contem a palavra «tenant»
                # e **nao** e um identificador — e por isso que o que se
                # verifica e a forma e a lista fechada, e nao uma palavra.)
                self.assertIsNone(re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", nome))
                etiqueta = re.search(r'="([^"]*)"', nome)
                if etiqueta:
                    self.assertIn(
                        etiqueta.group(1), set(DESFECHOS) | set(MOTIVOS_DE_RECUSA)
                    )


class TestDegradedTurns(unittest.TestCase):
    """A metrica que o KAM-025 deixou de fora **nasceu com o KAM-037**.

    Este ensaio media a ausencia, e a razao era boa: «uma metrica declarada e
    sempre a zero e pior do que uma metrica ausente» — a licao do
    `echo_latency_ms` do KAM-018. Deixou de valer no instante em que passou a
    existir caminho por onde um turno pode ficar degradado, e o que a ausencia
    media agora mede-se pelo outro lado: a metrica existe, leva o **motivo** por
    etiqueta, e **nao** leva o *tenant*.
    """

    def test_existe_desde_o_kam037_e_leva_o_motivo(self) -> None:
        import kamba_agr.metricas as modulo
        from kamba_agr.degradacao import MOTIVOS

        nomes = [
            getattr(modulo, nome)
            for nome in dir(modulo)
            if nome.startswith("METRICA_")
        ]
        self.assertIn("agr_degraded_turns_total", nomes)
        # O sinal que o KAM-025 deixou no lugar continua a existir: e o gatilho
        # de contrapressao do criterio 8, e nao foi substituido.
        self.assertIn(METRICA_CONTRAPRESSAO, nomes)
        metricas = modulo.MetricasDoAgr()
        for motivo in MOTIVOS:
            metricas.contar(modulo.METRICA_DEGRADADOS, motivo)
        exposicao = metricas.exposicao()
        for motivo in MOTIVOS:
            self.assertIn(f'motivo="{motivo}"', exposicao)

    def test_o_tenant_nao_e_etiqueta_desta_metrica(self) -> None:
        """A gramatica recusa-o pela **forma**, e nao por lista de proibidos."""
        import kamba_agr.metricas as modulo

        metricas = modulo.MetricasDoAgr()
        with self.assertRaises(modulo.EtiquetaInvalida):
            metricas.contar(
                modulo.METRICA_DEGRADADOS, "11111111-1111-4111-8111-111111111111"
            )


if __name__ == "__main__":
    unittest.main()
