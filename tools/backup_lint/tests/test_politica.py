"""Os predicados de backup (KAM-079).

Quatro classes, e a ordem e a das perguntas:

    TestOFunil            o gate do criterio 7 recusa o que tem de recusar?
    TestRestauroDevido    o predicado mensal, com o relogio acelerado
    TestIdadeDoWal        o alerta dispara onde o §9.2 diz?
    TestDebito            o orcamento do §8.2, e a regra dos 20%
    TestErasureLedger     a reaplicacao filtra pelo instante certo?

**O relogio entra sempre por parametro, e e a razao de esta suite existir.** Um
`now()` por dentro das funcoes obrigava a esperar 31 dias para provar que o
restauro esta em divida, ou a mentir ao relogio do sistema. Com o `agora` por
parametro, cada caso e uma linha.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import kamba_yaml
from backup_lint import politica

T0 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

#: A fixture do *erasure ledger* (criterio 8), no disco e nao num literal.
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "erasure_ledger.yaml"


class TestOFunil(unittest.TestCase):
    """O criterio 7: «enquanto nao houver `apd_ref`, `prod` com dados reais nao
    envia para ele»."""

    def test_sinteticos_saem_sempre(self) -> None:
        veredicto = politica.pode_enviar(classe_de_dados="synthetic")
        self.assertTrue(veredicto.permitido)
        self.assertIn("sintetic", veredicto.razao)

    def test_reais_sem_apd_ref_nao_saem(self) -> None:
        veredicto = politica.pode_enviar(classe_de_dados="real", destino="repo1")
        self.assertFalse(veredicto.permitido)
        self.assertIn("apd_ref", veredicto.razao)

    def test_reais_sem_destino_nomeiam_a_d1(self) -> None:
        """A razao distingue «falta a autorizacao» de «falta o destino».

        A diferenca decide se se abre um ticket ou se se espera por um parecer,
        e um booleano obrigava quem o le a reconstrui-la.
        """
        veredicto = politica.pode_enviar(classe_de_dados="real")
        self.assertFalse(veredicto.permitido)
        self.assertIn("KAM-105", veredicto.razao)

    def test_reais_com_apd_ref_saem(self) -> None:
        veredicto = politica.pode_enviar(
            classe_de_dados="real", apd_ref="APD/2026/0001", destino="repo1"
        )
        self.assertTrue(veredicto.permitido)
        self.assertIn("APD/2026/0001", veredicto.razao)

    def test_os_marcadores_nao_abrem_o_gate(self) -> None:
        """**O caso que importa mais.** Um `apd_ref: pendente` num ficheiro de
        configuracao parece uma referencia e abriria o gate inteiro.

        **Itera a lista inteira e nao uma amostra**, e a razao e um achado da
        revisao adversarial: a primeira versao escrevia oito cadeias a mao, duas
        das quais (`""` e `"  "`) nao sao marcadores — saem pelo `strip()` antes
        de a lista ser consultada. Dos dezasseis marcadores, **seis** estavam
        exercitados, e apagar os outros dez deixava a suite verde. Uma amostra
        escrita a mao prova os itens de que alguem se lembrou.
        """
        self.assertGreaterEqual(len(politica._NAO_SAO_REFERENCIA), 16)
        for marcador in sorted(politica._NAO_SAO_REFERENCIA):
            for forma in (marcador, marcador.upper(), f"  {marcador}  "):
                with self.subTest(marcador=forma):
                    self.assertIsNone(
                        politica.normalizar_apd_ref(forma),
                        f"`{forma}` passou por referencia",
                    )
                    veredicto = politica.pode_enviar(
                        classe_de_dados="real", apd_ref=forma, destino="repo1"
                    )
                    self.assertFalse(veredicto.permitido, forma)

    def test_o_vazio_nao_e_marcador_e_tambem_nao_abre_o_gate(self) -> None:
        """A outra metade do achado: `""` e `"  "` nao chegam a lista.

        Ficam num ensaio proprio porque o caminho e outro — o `strip()` recusa-os
        antes — e juntar os dois casos no mesmo ensaio foi o que fez a amostra
        parecer maior do que era.
        """
        for vazio in ("", "  ", "\t", None):
            with self.subTest(vazio=vazio):
                self.assertIsNone(politica.normalizar_apd_ref(vazio))
                self.assertFalse(
                    politica.pode_enviar(
                        classe_de_dados="real", apd_ref=vazio, destino="repo1"
                    ).permitido
                )

    def test_uma_classe_desconhecida_nega_por_omissao(self) -> None:
        """`kamba_data_klass=rael` nao e `synthetic`, e nao se trata como tal."""
        veredicto = politica.pode_enviar(classe_de_dados="rael")
        self.assertFalse(veredicto.permitido)
        self.assertIn("nega-se por omissao", veredicto.razao)

    def test_a_forma_da_referencia_e_estreita(self) -> None:
        """Uma referencia com espacos ou muito curta nao e uma referencia."""
        self.assertIsNone(politica.normalizar_apd_ref("ab"))
        self.assertIsNone(politica.normalizar_apd_ref("APD 2026 0001"))
        self.assertIsNone(politica.normalizar_apd_ref(False))
        self.assertEqual(
            politica.normalizar_apd_ref("  APD-2026-0001  "), "APD-2026-0001"
        )


class TestRestauroDevido(unittest.TestCase):
    def test_nunca_correu_esta_em_divida(self) -> None:
        """A rede de seguranca que nunca se ensaiou e a que mais precisa do
        ensaio. Tratar «nunca» como «ainda nao e tempo» deixava um repositorio
        recem-criado sem prova de restauro indefinidamente."""
        self.assertTrue(
            politica.restauro_devido(agora=T0, ultimo_em=None, periodo_dias=30)
        )

    def test_a_fronteira_dos_trinta_dias(self) -> None:
        self.assertFalse(
            politica.restauro_devido(
                agora=T0, ultimo_em=T0 - timedelta(days=29, hours=23), periodo_dias=30
            )
        )
        self.assertTrue(
            politica.restauro_devido(
                agora=T0, ultimo_em=T0 - timedelta(days=30), periodo_dias=30
            )
        )

    def test_e_idempotente(self) -> None:
        """Duas chamadas com o mesmo `agora` dao a mesma resposta.

        E o que permite ao agendador — quando existir — chamar isto a cada hora
        sem produzir dois restauros no mesmo dia.
        """
        ultimo = T0 - timedelta(days=31)
        primeira = politica.restauro_devido(agora=T0, ultimo_em=ultimo, periodo_dias=30)
        segunda = politica.restauro_devido(agora=T0, ultimo_em=ultimo, periodo_dias=30)
        self.assertEqual(primeira, segunda)

    def test_um_restauro_no_futuro_e_um_relogio_errado(self) -> None:
        with self.assertRaises(ValueError) as caso:
            politica.restauro_devido(
                agora=T0, ultimo_em=T0 + timedelta(days=1), periodo_dias=30
            )
        self.assertIn("relogio errado", str(caso.exception))

    def test_um_periodo_nao_positivo_recusa_se(self) -> None:
        with self.assertRaises(ValueError):
            politica.restauro_devido(agora=T0, ultimo_em=None, periodo_dias=0)

    def test_um_instante_sem_fuso_recusa_se(self) -> None:
        """Um `datetime` ingenuo compara-se com o de outra maquina e da a
        diferenca errada **sem avisar**."""
        with self.assertRaises(ValueError) as caso:
            politica.restauro_devido(
                agora=datetime(2026, 11, 1, 12, 0, 0), ultimo_em=None, periodo_dias=30
            )
        self.assertIn("ingenuo", str(caso.exception))

    def test_o_proximo_restauro_de_quem_nunca_correu_e_agora(self) -> None:
        self.assertEqual(
            politica.proximo_restauro(ultimo_em=None, periodo_dias=30, agora=T0), T0
        )
        self.assertEqual(
            politica.proximo_restauro(
                ultimo_em=T0 - timedelta(days=10), periodo_dias=30, agora=T0
            ),
            T0 + timedelta(days=20),
        )


class TestIdadeDoWal(unittest.TestCase):
    def test_nunca_arquivou_da_infinito_e_nao_zero(self) -> None:
        """**O caso que mais importa deste grupo.** Um zero aqui le-se como
        «acabou de arquivar», que e exactamente o estado em que o arquivo nunca
        funcionou — e o alerta nao disparava."""
        idade = politica.idade_do_wal_segundos(agora=T0, ultimo_wal_em=None)
        self.assertEqual(idade, float("inf"))
        self.assertTrue(
            politica.wal_em_alerta(agora=T0, ultimo_wal_em=None, limite_segundos=300)
        )

    def test_a_fronteira_dos_cinco_minutos_e_estrita(self) -> None:
        """O §9.2 escreve «> 5 min»: a fronteira exacta nao e um incidente."""
        self.assertFalse(
            politica.wal_em_alerta(
                agora=T0,
                ultimo_wal_em=T0 - timedelta(seconds=300),
                limite_segundos=300,
            )
        )
        self.assertTrue(
            politica.wal_em_alerta(
                agora=T0,
                ultimo_wal_em=T0 - timedelta(seconds=301),
                limite_segundos=300,
            )
        )

    def test_um_limite_nao_positivo_recusa_se(self) -> None:
        with self.assertRaises(ValueError):
            politica.wal_em_alerta(agora=T0, ultimo_wal_em=T0, limite_segundos=0)


class TestDebito(unittest.TestCase):
    def test_megabits_e_nao_megabytes(self) -> None:
        """Confundi-los da um factor de 8, e um factor de 8 num orcamento de RTO
        e a diferenca entre 30 minutos e 4 horas."""
        # 100 Mbps durante 1 s = 100 Mb = 12,5 MB = 12 500 000 octetos.
        self.assertAlmostEqual(
            politica.debito_mbps(bytes_lidos=12_500_000, segundos=1.0), 100.0
        )

    def test_o_orcamento_do_doc_09_reconcilia(self) -> None:
        """«BD <= 20 GB ~ 30 min em 100 Mbps». Verificado, e nao copiado.

        20 GB (10^9) a 100 Mbps = 20e9 x 8 / 100e6 = 1600 s = 26,7 min. O
        documento escreve «~ 30 min» e marca-o ESTIMATIVA: o orcamento tem
        folga de ~12%, e isso **esta dentro** dos 20% do criterio 4 — pelo que o
        orcamento nao se corrige por esta aritmetica.
        """
        segundos_teoricos = 20_000_000_000 * 8 / (100 * politica.BITS_POR_MEGABIT)
        self.assertAlmostEqual(segundos_teoricos, 1600.0)
        self.assertFalse(
            politica.orcamento_a_corrigir(
                medido=segundos_teoricos,
                orcamentado=1800.0,
                divergencia_maxima_pct=20.0,
            )
        )

    def test_a_divergencia_conta_nos_dois_sentidos(self) -> None:
        """Um restauro 40% mais **rapido** tambem invalida o orcamento: um
        orcamento folgado por 40% faz planear um RTO que nao se cumpre quando a
        base crescer."""
        self.assertTrue(
            politica.orcamento_a_corrigir(
                medido=1080.0, orcamentado=1800.0, divergencia_maxima_pct=20.0
            )
        )
        self.assertTrue(
            politica.orcamento_a_corrigir(
                medido=2520.0, orcamentado=1800.0, divergencia_maxima_pct=20.0
            )
        )

    def test_a_fronteira_dos_vinte_por_cento_e_estrita(self) -> None:
        """«divergir > 20%»: exactamente 20% nao corrige."""
        self.assertFalse(
            politica.orcamento_a_corrigir(
                medido=2160.0, orcamentado=1800.0, divergencia_maxima_pct=20.0
            )
        )

    def test_zero_segundos_nao_e_debito_infinito(self) -> None:
        with self.assertRaises(ValueError) as caso:
            politica.debito_mbps(bytes_lidos=1, segundos=0)
        self.assertIn("medicao que nao se fez", str(caso.exception))

    def test_divergencia_contra_zero_recusa_se(self) -> None:
        with self.assertRaises(ValueError):
            politica.divergencia_do_orcamento_pct(medido=1.0, orcamentado=0.0)

    def test_a_percentagem_publicada_e_esta_e_o_denominador_e_o_orcamento(self) -> None:
        """Os **-11,11%** que o criterio 4 e a linha de versoes publicam.

        Achado da revisao adversarial: trocar o denominador de `orcamentado`
        para `medido` deixava a suite inteira verde, porque nenhum ensaio
        afirmava uma percentagem — so booleanos, e os tres casos de
        `orcamento_a_corrigir` dao o mesmo booleano com os dois denominadores.
        Com a troca, o numero publicado passava de **-11,11%** para **-12,5%** e
        a fronteira dos 20% mudava de 2160 s para 2250 s sem nenhum vermelho.

        A divergencia e contra o **orcamento**, que e o que se quer saber: «o
        medido desvia-se X% do que estava planeado». Contra o medido responderia
        a outra pergunta, e o criterio 4 escreve a primeira.
        """
        self.assertAlmostEqual(
            politica.divergencia_do_orcamento_pct(medido=1600.0, orcamentado=1800.0),
            -11.111,
            places=3,
        )
        # A fronteira estrita dos 20%, que e o que o denominador decide.
        self.assertAlmostEqual(
            politica.divergencia_do_orcamento_pct(medido=2160.0, orcamentado=1800.0),
            20.0,
        )
        self.assertFalse(
            politica.orcamento_a_corrigir(
                medido=2160.0, orcamentado=1800.0, divergencia_maxima_pct=20.0
            ),
            "20% exactos nao corrigem: a fronteira e estrita",
        )
        self.assertTrue(
            politica.orcamento_a_corrigir(
                medido=2161.0, orcamentado=1800.0, divergencia_maxima_pct=20.0
            )
        )


class TestErasureLedger(unittest.TestCase):
    """O criterio 8: «com um sujeito apagado e um backup anterior ao apagamento,
    o *script* de reaplicacao remove o sujeito **(fixture)**».

    A fixture e um ficheiro no disco
    (`tests/fixtures/erasure_ledger.yaml`) e nao um literal nesta suite, e a
    diferenca importa: ela declara, por sujeito, a resposta esperada **e a
    razao**, pelo que a tabela de casos se le sem abrir este ficheiro — e e isso
    que o criterio pede quando escreve «(fixture)».
    """

    def _da_fixture(self) -> tuple[datetime, list[politica.Sujeito], dict[str, bool]]:
        dados = kamba_yaml.load_file(FIXTURE)
        restaurado_de = politica.ler_instante(str(dados["restaurado_de"]))
        ledger = [
            politica.Sujeito(
                str(s["subject_ref"]), politica.ler_instante(str(s["erased_at"]))
            )
            for s in dados["sujeitos"]
        ]
        esperado = {str(s["subject_ref"]): bool(s["reaplicar"]) for s in dados["sujeitos"]}
        return restaurado_de, ledger, esperado

    def _ledger(self) -> list[politica.Sujeito]:
        return [
            politica.Sujeito("bsuid-antes", T0 - timedelta(days=5)),
            politica.Sujeito("bsuid-depois-1", T0 + timedelta(days=1)),
            politica.Sujeito("bsuid-depois-2", T0 + timedelta(hours=2)),
        ]

    def test_a_fixture_decide_caso_a_caso(self) -> None:
        """Cada sujeito da fixture, contra o `reaplicar` que ela declara."""
        restaurado_de, ledger, esperado = self._da_fixture()
        reaplicados = {
            s.subject_ref
            for s in politica.sujeitos_a_reaplicar(
                ledger=ledger, restaurado_de=restaurado_de
            )
        }
        self.assertTrue(esperado, "fixture vazia nao e um zero util")
        for referencia, devia in esperado.items():
            with self.subTest(sujeito=referencia):
                self.assertEqual(referencia in reaplicados, devia)

    def test_a_fixture_cobre_as_duas_respostas_e_a_fronteira(self) -> None:
        """Uma fixture so com `reaplicar: true` passava com um predicado que
        devolvesse o ledger inteiro."""
        dados = kamba_yaml.load_file(FIXTURE)
        respostas = {bool(s["reaplicar"]) for s in dados["sujeitos"]}
        self.assertEqual(respostas, {True, False})
        instantes = {str(s["erased_at"]) for s in dados["sujeitos"]}
        self.assertIn(str(dados["restaurado_de"]), instantes, "falta a fronteira exacta")
        for sujeito in dados["sujeitos"]:
            self.assertTrue(str(sujeito.get("razao", "")).strip(), sujeito)

    def test_nenhum_sujeito_da_fixture_parece_um_numero(self) -> None:
        """O repositorio e publico: um numero angolano real na fixture era um
        dado pessoal versionado. Nove digitos seguidos nao passam."""
        dados = kamba_yaml.load_file(FIXTURE)
        for sujeito in dados["sujeitos"]:
            with self.subTest(sujeito=sujeito["subject_ref"]):
                self.assertNotRegex(str(sujeito["subject_ref"]), r"\d{6,}")

    def test_so_quem_foi_apagado_depois_do_backup(self) -> None:
        """O backup e de T. Quem foi apagado em T' > T **volta** com o
        restauro, porque em T ainda estava la."""
        reaplicar = politica.sujeitos_a_reaplicar(
            ledger=self._ledger(), restaurado_de=T0
        )
        self.assertEqual(
            [s.subject_ref for s in reaplicar], ["bsuid-depois-2", "bsuid-depois-1"]
        )

    def test_a_ordem_e_cronologica(self) -> None:
        """Reaplicar por ordem cronologica e o que mantem o `audit_log` do
        restauro a contar a mesma historia que o original."""
        reaplicar = politica.sujeitos_a_reaplicar(
            ledger=self._ledger(), restaurado_de=T0
        )
        instantes = [s.erased_at for s in reaplicar]
        self.assertEqual(instantes, sorted(instantes))

    def test_quem_ja_nao_esta_no_backup_nao_se_reaplica(self) -> None:
        """Nao e por elegancia: um *script* que reaplicasse o ledger inteiro a
        cada restauro faria `DELETE` sobre linhas inexistentes e, num ledger
        grande, isso transforma um restauro de 30 minutos num de horas."""
        reaplicar = politica.sujeitos_a_reaplicar(
            ledger=self._ledger(), restaurado_de=T0 + timedelta(days=30)
        )
        self.assertEqual(reaplicar, [])

    def test_a_fronteira_exacta_nao_se_reaplica(self) -> None:
        """Apagado **no** instante do backup: a linha nao esta na copia."""
        ledger = [politica.Sujeito("bsuid-na-fronteira", T0)]
        self.assertEqual(
            politica.sujeitos_a_reaplicar(ledger=ledger, restaurado_de=T0), []
        )

    def test_e_idempotente(self) -> None:
        """Nao escreve nada e nao le relogio: e o que permite re-executar um
        restauro interrompido."""
        ledger = self._ledger()
        primeira = politica.sujeitos_a_reaplicar(ledger=ledger, restaurado_de=T0)
        segunda = politica.sujeitos_a_reaplicar(ledger=ledger, restaurado_de=T0)
        self.assertEqual(primeira, segunda)

    def test_um_instante_do_ledger_sem_fuso_recusa_se(self) -> None:
        ledger = [politica.Sujeito("bsuid-ingenuo", datetime(2026, 11, 2, 0, 0))]
        with self.assertRaises(ValueError):
            politica.sujeitos_a_reaplicar(ledger=ledger, restaurado_de=T0)


class TestAncoraDoAuditLog(unittest.TestCase):
    def test_a_consulta_nao_tem_now(self) -> None:
        """**O ponto, e nao uma formalidade.** Uma consulta com `now()` por
        dentro nao se consegue ensaiar sobre uma fixture com datas fixas, e um
        ensaio que nao se consegue acelerar nao se corre."""
        self.assertNotIn("now()", politica.SQL_ANCORA_DO_AUDIT_LOG)
        self.assertNotIn("current_timestamp", politica.SQL_ANCORA_DO_AUDIT_LOG.lower())
        self.assertIn("$1", politica.SQL_ANCORA_DO_AUDIT_LOG)
        self.assertIn("$2", politica.SQL_ANCORA_DO_AUDIT_LOG)

    def test_a_ancora_e_por_tenant(self) -> None:
        """O encadeamento e por tenant (`docs/tecnica/08` §6): uma ancora global
        nao prova cadeia nenhuma."""
        self.assertIn("GROUP BY tenant_id", politica.SQL_ANCORA_DO_AUDIT_LOG)

    def test_le_a_coluna_canonica_do_tempo(self) -> None:
        """`criado_at`, e nao `created_at`: o nome canonico esta na revisao
        `0006` do `audit_log` (`docs/tecnica/08` §6)."""
        self.assertIn("criado_at", politica.SQL_ANCORA_DO_AUDIT_LOG)
        self.assertNotIn("created_at", politica.SQL_ANCORA_DO_AUDIT_LOG)

    # -----------------------------------------------------------------
    # As quatro propriedades que faltavam, e porque estao prendidas assim
    # -----------------------------------------------------------------
    #
    # A revisao adversarial mutou esta consulta em quatro pontos e **os quatro
    # sobreviveram**: os ensaios acima sao greps de subcadeia («nao tem
    # `now()`», «e por tenant», «le `criado_at`») e nenhum media a propriedade
    # que o `docs/tecnica/08` §6 pede — a ancora e o **ultimo** `row_hash` da
    # janela, por tenant, numa janela meio-aberta.
    #
    # A propriedade foi medida contra um PostgreSQL 18 real, com cinco linhas de
    # fixture (tres elos no dia 1 para um tenant, com o primeiro a ter o hash
    # alfabeticamente **menor** de proposito, mais um elo exactamente na
    # fronteira `$2` e um segundo tenant). A consulta do ramo devolve `ccc`, que
    # e o ultimo elo do dia; cada mutacao devolve outra coisa:
    #
    #   consulta do ramo         -> ccc @ 23:00     (o ultimo elo)
    #   ORDER BY ... ASC, id ASC -> aaa             (o primeiro elo)
    #   min(row_hash)            -> aaa             (o menor, nao o ultimo)
    #   criado_at <= $2          -> zzz @ 00:00     (a linha do dia seguinte)
    #   min(criado_at)           -> 01:00           (o inicio, nao o fim)
    #
    # O comando e a saida estao em `docs/evidencia/KAM-079.md` §3.5.
    #
    # **Porque e que os ensaios sao textuais e nao executam a consulta:** o
    # gate 4 nao tem base de dados, e um ensaio que precise de contentor nao
    # corre nele. O que estes ensaios fazem e prender **o texto exacto que cada
    # mutacao medida tem de quebrar** — e isso e menos do que executar o
    # predicado, dito em voz alta. O ensaio que o executa pertence ao gate 8,
    # que tem Postgres, e a quem for dono do escritor da tabela (**KAM-070**).

    def test_a_ancora_e_o_ultimo_elo_e_nao_o_primeiro(self) -> None:
        """A mutacao `ASC, id ASC` devolve `aaa` em vez de `ccc` — medido."""
        self.assertIn(
            "ORDER BY criado_at DESC, id DESC", politica.SQL_ANCORA_DO_AUDIT_LOG
        )
        self.assertNotIn("criado_at ASC", politica.SQL_ANCORA_DO_AUDIT_LOG)

    def test_a_ancora_escolhe_pela_ordem_e_nao_pelo_valor_do_hash(self) -> None:
        """A mutacao `min(row_hash)` devolve `aaa`: o menor nao e o ultimo.

        Um `row_hash` e opaco, pelo que `min`/`max` sobre ele nao significam
        nada — e e exactamente por serem plausiveis a ler que precisam de
        ensaio.
        """
        sql = politica.SQL_ANCORA_DO_AUDIT_LOG
        self.assertIn("(array_agg(row_hash ORDER BY", sql)
        self.assertIn("))[1] AS row_hash", sql)
        self.assertNotIn("min(row_hash)", sql)
        self.assertNotIn("max(row_hash)", sql)

    def test_a_janela_e_meio_aberta(self) -> None:
        """A mutacao `<=` apanha a linha das 00:00 do dia seguinte — medido.

        Com os dois lados fechados, duas ancoras diarias consecutivas partilham
        uma linha, e a cadeia de uma delas fica a apontar para a outra.
        """
        sql = politica.SQL_ANCORA_DO_AUDIT_LOG
        self.assertIn("criado_at >= $1", sql)
        self.assertIn("criado_at <  $2", sql)
        self.assertNotIn("criado_at <= $2", sql)

    def test_o_instante_ancorado_e_o_fim_da_janela_e_nao_o_inicio(self) -> None:
        """A mutacao `min(criado_at)` devolve as 01:00 em vez das 23:00."""
        sql = politica.SQL_ANCORA_DO_AUDIT_LOG
        self.assertIn("max(criado_at) AS ancorado_at", sql)
        self.assertNotIn("min(criado_at)", sql)


class TestLerInstante(unittest.TestCase):
    def test_aceita_o_z_do_pgbackrest(self) -> None:
        """O `pgbackrest info --output=json` usa `Z`, e o `fromisoformat` do
        Python so a aceita desde a 3.11."""
        self.assertEqual(
            politica.ler_instante("2026-11-01T12:00:00Z"),
            datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc),
        )

    def test_normaliza_para_utc(self) -> None:
        """Dois instantes com fusos diferentes comparam-se bem e **imprimem-se**
        de forma que engana quem le o relatorio."""
        lido = politica.ler_instante("2026-11-01T13:00:00+01:00")
        self.assertEqual(lido.tzinfo, timezone.utc)
        self.assertEqual(lido.hour, 12)

    def test_um_instante_sem_fuso_recusa_se(self) -> None:
        with self.assertRaises(ValueError):
            politica.ler_instante("2026-11-01T12:00:00")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
