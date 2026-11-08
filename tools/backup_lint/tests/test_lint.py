"""Testes do `backup_lint` — as cinco superficies do KAM-079.

    TestArvoreReal        a arvore deste repositorio passa, e leu alguma coisa?
    TestLeitura           uma superficie que nao se le recusa-se a medir?
    TestConf              o leitor de `.conf` apanha o que tem de apanhar?
    TestReconciliacao     os numeros do bloco reconciliam com os ficheiros?
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from backup_lint import lint

RAIZ = Path(__file__).resolve().parents[3]


class _ComCopia(unittest.TestCase):
    """Copia so o que o `varrer` le, para poder mutilar sem tocar na arvore."""

    def copiar(self) -> Path:
        pasta = Path(tempfile.mkdtemp(prefix="backup-lint-teste-"))
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        for relativo in (
            lint.COBERTURA,
            lint.PGBACKREST,
            lint.ARQUIVO,
            lint.CATALOGO,
            lint.INVENTARIO_DE_SEGREDOS,
        ):
            alvo = pasta / relativo
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(RAIZ / relativo, alvo)
        shutil.copytree(RAIZ / lint.RUNBOOKS, pasta / lint.RUNBOOKS)
        return pasta


class TestArvoreReal(unittest.TestCase):
    def test_a_arvore_real_passa(self) -> None:
        achados, numeros = lint.varrer(RAIZ)
        self.assertEqual([str(a) for a in achados], [])
        # E **leu** alguma coisa: um verde sobre zero itens de cobertura le-se
        # como «esta tudo bem».
        self.assertGreater(numeros["itens"], 0)
        self.assertGreater(numeros["chaves_do_pgbackrest"], 0)
        self.assertGreater(numeros["chaves_do_arquivo"], 0)
        self.assertEqual(numeros["regras"], len(lint.REGRAS))

    def test_nao_ha_destino_decidido_hoje(self) -> None:
        """A premissa de todo este ticket, prendida num ensaio.

        O dia em que houver destino, este ensaio fica vermelho — e e o sinal
        certo: a seccao de verificacao do bloco, o `exposta_por` das quatro
        metricas e metade das caixas mudam com ele.
        """
        _, numeros = lint.varrer(RAIZ)
        self.assertEqual(
            numeros["destinos"],
            0,
            "ha um destino decidido. Se e verdade, a D1 fechou: releia a seccao "
            "de verificacao do KAM-079 antes de corrigir este numero",
        )
        self.assertGreater(numeros["destinos_por_decidir"], 0)

    def test_os_itens_configurados_contam_se_em_voz_alta(self) -> None:
        """Um verde sobre itens que nunca correram nao e o mesmo verde."""
        _, numeros = lint.varrer(RAIZ)
        self.assertGreater(numeros["configurados"], 0)
        self.assertEqual(
            numeros["itens"],
            numeros["cobertos"] + numeros["configurados"] + numeros["por_cobrir"],
        )


class TestLeitura(_ComCopia):
    def test_sem_cobertura_nao_passa_em_silencio(self) -> None:
        copia = self.copiar()
        (copia / lint.COBERTURA).unlink()
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.varrer(copia)

    def test_sem_pgbackrest_nao_passa_em_silencio(self) -> None:
        copia = self.copiar()
        (copia / lint.PGBACKREST).unlink()
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.varrer(copia)

    def test_sem_catalogo_nao_passa_em_silencio(self) -> None:
        copia = self.copiar()
        (copia / lint.CATALOGO).unlink()
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.varrer(copia)

    def test_sem_inventario_de_segredos_nao_passa_em_silencio(self) -> None:
        copia = self.copiar()
        (copia / lint.INVENTARIO_DE_SEGREDOS).unlink()
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.varrer(copia)

    def test_uma_chave_de_topo_em_falta_recusa_se(self) -> None:
        copia = self.copiar()
        caminho = copia / lint.COBERTURA
        caminho.write_text(
            caminho.read_text(encoding="utf-8").replace("\nciclo:", "\nciclo_antigo:"),
            encoding="utf-8",
            newline="\n",
        )
        with self.assertRaises(lint.ConfiguracaoInvalida) as caso:
            lint.varrer(copia)
        self.assertIn("ciclo", str(caso.exception))


class TestConf(unittest.TestCase):
    """O leitor de `.conf`, que nao e um parser de INI e diz porque."""

    def _escrever(self, texto: str) -> Path:
        pasta = Path(tempfile.mkdtemp(prefix="backup-lint-conf-"))
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        caminho = pasta / "x.conf"
        caminho.write_text(texto, encoding="utf-8", newline="\n")
        return caminho

    def test_le_chave_e_valor_com_e_sem_espacos(self) -> None:
        caminho = self._escrever("[s]\na=1\nb = 2\n# comentario\n\n")
        self.assertEqual(lint._ler_conf(caminho, "x"), {"a": "1", "b": "2"})

    def test_uma_chave_repetida_recusa_se(self) -> None:
        """A ultima ganharia em silencio, e um numero que se le duas vezes com
        valores diferentes nao e um numero."""
        caminho = self._escrever("a=1\na=2\n")
        with self.assertRaises(lint.ConfiguracaoInvalida) as caso:
            lint._ler_conf(caminho, "x")
        self.assertIn("repetida", str(caso.exception))

    def test_uma_linha_sem_igual_recusa_se(self) -> None:
        caminho = self._escrever("a=1\nisto nao e uma chave\n")
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint._ler_conf(caminho, "x")

    def test_um_conf_vazio_nao_e_um_zero_util(self) -> None:
        caminho = self._escrever("# so comentarios\n")
        with self.assertRaises(lint.ConfiguracaoInvalida) as caso:
            lint._ler_conf(caminho, "x")
        self.assertIn("zero util", str(caso.exception))

    def test_os_segundos_leem_se_com_e_sem_unidade(self) -> None:
        self.assertEqual(lint._segundos("60s"), 60)
        self.assertEqual(lint._segundos("60"), 60)
        self.assertEqual(lint._segundos("1min"), 60)
        self.assertEqual(lint._segundos("'60s'"), 60)
        self.assertIsNone(lint._segundos("um minuto"))

    def test_milissegundos_nao_se_arredondam_para_plausivel(self) -> None:
        """`60000ms` nao e 60 s para este leitor, e e de proposito: devolver 60
        fazia uma unidade errada passar o *lint*."""
        self.assertEqual(lint._segundos("60000ms"), 0)


class TestReconciliacao(unittest.TestCase):
    """Os numeros do bloco contra os ficheiros — a parte que nao e opiniao."""

    def setUp(self) -> None:
        self.dados = lint.ler(RAIZ)

    def test_os_trinta_e_cinco_dias_sao_cinco_completos_semanais(self) -> None:
        ciclo = self.dados.cobertura["ciclo"]
        self.assertEqual(ciclo["completo"], "semanal")
        self.assertEqual(ciclo["retencao_completos"] * 7, ciclo["retencao_dias"])
        self.assertEqual(ciclo["retencao_dias"], 35, "criterio 1")

    def test_o_pitr_e_de_sete_dias_nas_duas_superficies(self) -> None:
        self.assertEqual(self.dados.cobertura["ciclo"]["pitr_dias"], 7)
        self.assertEqual(self.dados.pgbackrest["repo1-retention-archive"], "7")

    def test_o_archive_timeout_e_de_sessenta_segundos(self) -> None:
        self.assertEqual(
            lint._segundos(self.dados.arquivo["archive_timeout"]),
            60,
            "`docs/tecnica/09` §8.1, linha «WAL»",
        )

    def test_o_limite_do_alerta_e_o_rpo(self) -> None:
        """O alerta dispara exactamente quando o RPO deixa de estar garantido.

        Dois numeros diferentes querem dizer que ele dispara antes ou depois
        disso, e nenhum documento o diz.
        """
        self.assertEqual(
            self.dados.cobertura["alerta_do_wal"]["limite_segundos"],
            self.dados.cobertura["alvos"]["rpo_segundos"],
        )
        self.assertEqual(self.dados.cobertura["alvos"]["rpo_segundos"], 300)

    def test_o_rto_do_doc_00_sao_duas_horas(self) -> None:
        self.assertEqual(self.dados.cobertura["alvos"]["rto_segundos"], 7200)

    def test_nenhuma_chave_sensivel_esta_no_ficheiro(self) -> None:
        """O repositorio e publico. Isto repete a regra `segredo-em-claro` de
        proposito: a regra pode ser desligada do `REGRAS`, e este ensaio nao.

        **O predicado inverteu-se, e a razao esta medida no `lint.py`:** o
        pgBackRest nao expande `${...}` dentro do ficheiro, pelo que uma
        referencia escrita aqui seria lida como valor. A chave tem de estar
        **ausente**.
        """
        for chave in lint.CHAVES_DO_AMBIENTE:
            with self.subTest(chave=chave):
                self.assertNotIn(
                    chave,
                    self.dados.pgbackrest,
                    f"`{chave}` esta no ficheiro: o pgBackRest le o valor "
                    f"literalmente. Tem de vir do `{lint.nome_no_ambiente(chave)}`",
                )

    def test_o_cabecalho_nomeia_o_ambiente_de_cada_chave_ausente(self) -> None:
        """A metade que impede a outra de ser uma chave esquecida."""
        texto = (self.dados.raiz / lint.PGBACKREST).read_text(encoding="utf-8")
        for chave in lint.CHAVES_DO_AMBIENTE:
            with self.subTest(chave=chave):
                self.assertIn(lint.nome_no_ambiente(chave), texto)

    def test_o_nome_no_ambiente_segue_a_regra_do_pgbackrest(self) -> None:
        """Derivado e nao tabelado: maiusculas e `-` para `_`, com prefixo.

        Os tres casos sao os que o binario aceitou (pgBackRest 2.45): o
        `PGBACKREST_REPO1_PATH` e o `PGBACKREST_REPO1_CIPHER_PASS` foram medidos
        a funcionar, e o terceiro prova que a derivacao atravessa dois hifenes.
        """
        self.assertEqual(
            lint.nome_no_ambiente("repo1-path"), "PGBACKREST_REPO1_PATH"
        )
        self.assertEqual(
            lint.nome_no_ambiente("repo1-cipher-pass"),
            "PGBACKREST_REPO1_CIPHER_PASS",
        )
        self.assertEqual(
            lint.nome_no_ambiente("repo1-host-user"), "PGBACKREST_REPO1_HOST_USER"
        )

    def test_so_a_passphrase_e_tratada_como_segredo(self) -> None:
        """Um FQDN, um utilizador, dois caminhos e um nome de base nao o sao.

        Tratar tudo como segredo faz o inventario deixar de dizer o que protege,
        e foi um achado da revisao adversarial: o `pg1-database` estava na lista
        de «chaves de segredo».
        """
        self.assertEqual(lint.CHAVES_QUE_SAO_SEGREDO, ("repo1-cipher-pass",))
        for chave in lint.CHAVES_QUE_SAO_SEGREDO:
            self.assertIn(chave, lint.CHAVES_DO_AMBIENTE)

    def test_o_comando_do_arquivo_nao_leva_opcao_que_nao_existe(self) -> None:
        """Medido com o binario: `--async` da «invalid option» e o arquivo morre.

            $ pgbackrest --stanza=k archive-push --async /tmp/x
            ERROR: [031]: invalid option '--async'
            $ pgbackrest --stanza=k archive-push --archive-async /tmp/x
            ERROR: [037]: ... requires option 'pg1-path'   # a opcao e valida

        O ensaio esta aqui e nao so na regra porque esta linha atravessou cinco
        superficies sem que nenhuma olhasse para ela.
        """
        comando = self.dados.arquivo["archive_command"]
        self.assertNotIn("--async", comando)
        self.assertIn("archive-push", comando)
        self.assertIn("%p", comando)
        self.assertIn("--stanza=kamba", comando)

    def test_a_retencao_do_arquivo_e_por_diferencial_e_nao_por_completo(self) -> None:
        """A ajuda do binario, textual, e porque isto nao e uma preferencia.

        «If set to full pgBackRest will keep archive logs for the number of full
        backups defined by repo-retention-archive. If set to diff ... for the
        number of full and differential backups» — pgBackRest 2.45,
        `pgbackrest help expire repo-retention-archive-type`.

        Com `full` e `repo1-retention-archive=7` acima dos 5 completos retidos,
        retem-se o WAL de **todos** eles: 35 dias de WAL contra os «WAL 7 dias»
        do `docs/tecnica/08` §11. E sobre-retencao de dados pessoais.
        """
        self.assertEqual(
            self.dados.pgbackrest["repo1-retention-archive-type"], "diff"
        )
        self.assertEqual(self.dados.cobertura["ciclo"]["diferencial"], "diario")
        self.assertEqual(
            int(self.dados.pgbackrest["repo1-retention-archive"]),
            self.dados.cobertura["ciclo"]["pitr_dias"],
            "com um diferencial diario, N diferenciais sao N dias",
        )

    def test_as_tres_bases_do_criterio_estao_na_cobertura(self) -> None:
        itens = {str(l["item"]) for l in self.dados.cobertura["cobertura"]}
        for base in lint.BASES_EXIGIDAS:
            self.assertIn(f"base {base}", itens)

    def test_a_cifra_e_aes_256_nas_duas_superficies(self) -> None:
        self.assertEqual(
            self.dados.cobertura["ciclo"]["cifra"],
            self.dados.pgbackrest["repo1-cipher-type"],
        )
        self.assertTrue(
            self.dados.pgbackrest["repo1-cipher-type"].startswith(
                lint.PREFIXO_DA_CIFRA
            )
        )

    def test_o_agendador_esta_ausente_e_tem_credor(self) -> None:
        """A metade de «mensal automatico» que este ticket nao entrega.

        Fica num ensaio e nao so na prosa porque o dia em que o agendador
        nascer, este vermelho e o sinal de que a caixa do criterio 5 muda.
        """
        restauro = self.dados.cobertura["restauro"]
        self.assertEqual(restauro["agendador"], "ausente")
        self.assertTrue(str(restauro["credor_do_agendador"]).strip())
        self.assertEqual(restauro["periodo_dias"], 30)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
