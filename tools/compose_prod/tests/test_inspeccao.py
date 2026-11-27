"""O ensaio do `docker inspect` e os ficheiros de segredos, sem Docker (KAM-260).

O ensaio a serio (`python -m compose_prod inspeccao`, e o `--canario` dele)
precisa do Docker e corre no gate 6. Aqui fica o que se prova sem ele: que se
procura o que se deve procurar, que um achado nunca imprime um valor, que o
ficheiro que o lancador carrega se le como se escreveu, e que o compose real
tem a forma que o ensaio mede.

A pergunta e a do resto desta pasta: o que faria isto passar com o codigo
apagado? Um `procurar_valores` que devolvesse `[]` falha o segundo teste; um
compose que voltasse a pôr um segredo no `environment:` falha o da arvore real.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from compose_prod import inspeccao, segredos
from compose_prod.egress_dez import MARCADORES

RAIZ = Path(__file__).resolve().parents[3]

#: O que nunca pode estar num `environment:` de `prod`: um segredo do cofre.
SEGREDO_NO_AMBIENTE = re.compile(
    r"\$\{(?:KAMBA_SECRET_|POSTGRES_PASSWORD\b|CHATWOOT_DB_PASSWORD\b|CHATWOOT_SECRET_KEY_BASE\b"
    r"|[A-Z_]*_DB_URL\b)"
)


class TestAmbienteDeTeste(unittest.TestCase):
    def setUp(self) -> None:
        self.ids = inspeccao.ids_do_inventario(RAIZ)
        texto = (RAIZ / inspeccao.PROD).read_text(encoding="utf-8")
        self.variaveis = inspeccao.variaveis_do_compose(texto)
        self.ambiente, self.procurar = inspeccao.ambiente_de_teste(self.ids, self.variaveis)

    def test_le_o_inventario_inteiro(self) -> None:
        contadas = len(re.findall(r"^  - id: ", (RAIZ / inspeccao.INVENTARIO).read_text(encoding="utf-8"), re.M))
        self.assertEqual(len(self.ids), contadas)
        self.assertGreater(len(self.ids), 40)

    def test_cada_segredo_e_o_anterior_tem_valor_proprio(self) -> None:
        for ident in self.ids:
            actual = self.ambiente[f"KAMBA_SECRET_{ident.upper()}"]
            anterior = self.ambiente[f"KAMBA_SECRET_{ident.upper()}_ANTERIOR"]
            self.assertNotEqual(actual, anterior)
            self.assertEqual(self.procurar[actual], ident)
        valores = list(self.procurar)
        self.assertEqual(len(valores), len(set(valores)), "dois segredos com o mesmo valor")

    def test_os_valores_nascem_em_cada_execucao(self) -> None:
        outro, _ = inspeccao.ambiente_de_teste(self.ids, self.variaveis)
        chave = f"KAMBA_SECRET_{self.ids[0].upper()}"
        self.assertNotEqual(self.ambiente[chave], outro[chave])
        self.assertRegex(self.ambiente[chave], r"^[A-Z2-7]{32}$")

    def test_a_cadeia_de_ligacao_leva_a_senha_do_papel_que_nomeia(self) -> None:
        # «o deploy passa a cadeia de ligacao do kamba_batch» -> db_batch_password.
        cadeia = self.ambiente["KAMBA_PUBLICADOR_DB_URL"]
        self.assertIn(self.ambiente["KAMBA_SECRET_DB_BATCH_PASSWORD"], cadeia)

    def test_os_segredos_com_instancia_procuram_se_pelo_nome(self) -> None:
        valor = self.ambiente["KAMBA_SECRET_LLM_PROVIDER_KEY__anthropic"]
        self.assertEqual(self.procurar[valor], "llm_provider_key/anthropic")

    def test_um_utilizador_nao_e_segredo(self) -> None:
        self.assertNotIn(self.ambiente.get("POSTGRES_USER"), self.procurar)


class TestProcurarValores(unittest.TestCase):
    def _inspeccao(self, **config) -> dict:
        base = {"Labels": {"com.docker.compose.service": "agr"}, "Env": ["HOST=0.0.0.0"]}
        base.update(config)
        return {"Name": "/kamba-agr-1", "Config": base, "Mounts": [{"Source": "/run/kamba/segredos/agr.env"}]}

    def test_apanha_no_ambiente_nas_etiquetas_e_no_comando(self) -> None:
        valor = "VALORDETESTEVALORDETESTE"
        inspeccoes = [
            self._inspeccao(Env=[f"X={valor}"]),
            self._inspeccao(Labels={"com.docker.compose.service": "gwy", "k": f"a{valor}b"}),
            self._inspeccao(Cmd=["--senha", f"--x={valor}"]),
        ]
        achados = inspeccao.procurar_valores(inspeccoes, {valor: "queue_password"})
        self.assertEqual(
            sorted((a.servico, a.campo) for a in achados),
            [("agr", "Config.Cmd[1]"), ("agr", "Config.Env[X]"), ("gwy", "Config.Labels.k")],
        )

    def test_o_achado_nomeia_e_nunca_mostra_o_valor(self) -> None:
        valor = "OUTROVALORDETESTEOUTRO"
        (achado,) = inspeccao.procurar_valores(
            [self._inspeccao(Env=[f"KAMBA_SECRET_COM_INTERNAL_TOKEN={valor}"])], {valor: "x"}
        )
        self.assertNotIn(valor, str(achado))
        self.assertIn("KAMBA_SECRET_COM_INTERNAL_TOKEN", str(achado))

    def test_apanha_tambem_numa_chave(self) -> None:
        valor = "VALORNUMACHAVEVALORNUMA"
        achados = inspeccao.procurar_valores(
            [self._inspeccao(Tmpfs={f"/tmp/{valor}": ""})], {valor: "x"}
        )
        self.assertEqual([a.campo for a in achados], [f"Config.Tmpfs./tmp/{valor} (chave)"])

    def test_o_caminho_da_montagem_nao_e_achado(self) -> None:
        self.assertEqual(
            inspeccao.procurar_valores([self._inspeccao()], {"NAOAPARECE": "x"}), []
        )


class TestInterpolar(unittest.TestCase):
    def test_as_formas_do_compose(self) -> None:
        ambiente = {"A": "1", "VAZIO": ""}
        self.assertEqual(segredos.interpolar("${A:?m}", ambiente), "1")
        self.assertEqual(segredos.interpolar("x${FALTA:-d}y", ambiente), "xdy")
        self.assertEqual(segredos.interpolar("${VAZIO:-d}", ambiente), "d")
        self.assertEqual(segredos.interpolar("${VAZIO-d}", ambiente), "")
        self.assertEqual(segredos.interpolar("$${A}", ambiente), "${A}")
        self.assertEqual(segredos.interpolar("redis://:${A:?m}@queue:6379", ambiente), "redis://:1@queue:6379")

    def test_o_obrigatorio_em_falta_nomeia_a_variavel_e_nao_um_valor(self) -> None:
        with self.assertRaises(segredos.SegredoEmFalta) as erro:
            segredos.interpolar("${KAMBA_SECRET_COM_INTERNAL_TOKEN:?o cofre entrega o token}", {"OUTRA": "segredo"})
        self.assertIn("KAMBA_SECRET_COM_INTERNAL_TOKEN", str(erro.exception))
        self.assertNotIn("segredo'", str(erro.exception))
        with self.assertRaises(segredos.SegredoEmFalta):
            segredos.interpolar("${KAMBA_SECRET_COM_INTERNAL_TOKEN:?m}", {"KAMBA_SECRET_COM_INTERNAL_TOKEN": ""})


class TestFormasRecusadas(unittest.TestCase):
    """O que o compose interpola e o gravador nao saberia seguir (revisao adversarial)."""

    def test_recusa_o_mais_e_a_omissao_com_outra_variavel(self) -> None:
        for modelo in ("${A:+x}", "${A+x}", "${Z:-${B}}", "a$", "${A"):
            with self.subTest(modelo=modelo), self.assertRaises(segredos.ConfiguracaoInvalida):
                segredos.interpolar(modelo, {"A": "1", "B": "2"})

    def test_o_compose_real_so_usa_formas_que_o_gravador_segue(self) -> None:
        for servico, variaveis in segredos.declarados(RAIZ).items():
            for nome, modelo in variaveis.items():
                with self.subTest(servico=servico, nome=nome):
                    segredos.interpolar(modelo, {k: "v" for k in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", modelo)})


class TestDestino(unittest.TestCase):
    def test_recusa_o_destino_vazio_e_o_repositorio(self) -> None:
        # `--destino "$VAR"` com a variavel vazia vale `.`.
        for destino in (Path(""), Path("."), RAIZ, RAIZ / "tools", RAIZ / "infra" / "segredos"):
            with self.subTest(destino=str(destino)), self.assertRaises(segredos.ConfiguracaoInvalida):
                segredos.escrever(RAIZ, destino, {}, dono=False)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "corre como root")
    def test_sem_root_recusa_dar_os_ficheiros_aos_servicos(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            with self.assertRaises(segredos.ConfiguracaoInvalida) as erro:
                segredos.escrever(RAIZ, Path(pasta) / "s", {}, dono=True)
            self.assertIn("root", str(erro.exception))
            self.assertFalse((Path(pasta) / "s").exists())


class TestFicheiro(unittest.TestCase):
    def setUp(self) -> None:
        self.ids = inspeccao.ids_do_inventario(RAIZ)
        texto = (RAIZ / inspeccao.PROD).read_text(encoding="utf-8")
        self.ambiente, _ = inspeccao.ambiente_de_teste(
            self.ids, inspeccao.variaveis_do_compose(texto)
        )
        self.pasta = tempfile.TemporaryDirectory(prefix="kamba-segredos-teste-")
        self.destino = Path(self.pasta.name) / "s"

    def tearDown(self) -> None:
        self.pasta.cleanup()

    def test_um_ficheiro_por_servico_sem_cr_e_com_o_modo(self) -> None:
        escritos = segredos.escrever(RAIZ, self.destino, self.ambiente, dono=False)
        self.assertEqual(set(escritos), set(segredos.declarados(RAIZ)))
        for caminho in escritos.values():
            bruto = caminho.read_bytes()
            # Medido no KAM-260: no Windows o `os.open` sem `O_BINARY` escrevia
            # `\r\n`, e o `\r` ficava no fim de cada valor.
            self.assertNotIn(b"\r", bruto, caminho.name)
            if os.name == "posix":
                self.assertEqual(caminho.stat().st_mode & 0o777, 0o400, caminho.name)
        fila = escritos["queue"].read_text(encoding="utf-8")
        self.assertIn(f"REDISCLI_AUTH='{self.ambiente['KAMBA_SECRET_QUEUE_PASSWORD']}'\n", fila)

    def test_um_segredo_em_falta_nao_deixa_ficheiro_nenhum(self) -> None:
        incompleto = {k: v for k, v in self.ambiente.items() if k != "KAMBA_SECRET_QUEUE_PASSWORD"}
        with self.assertRaises(segredos.SegredoEmFalta):
            segredos.escrever(RAIZ, self.destino, incompleto, dono=False)
        self.assertFalse(self.destino.exists() and any(self.destino.iterdir()))

    def test_as_aspas_nao_deixam_o_shell_expandir_nada(self) -> None:
        texto = segredos.conteudo({"X": "a'b $HOME `id` \\ c"})
        self.assertEqual(texto, "X='a'\\''b $HOME `id` \\ c'\n")

    @unittest.skipUnless(shutil.which("sh") and os.name == "posix", "precisa de sh")
    def test_o_lancador_carrega_o_que_o_gravador_escreveu(self) -> None:
        valor = "a'b $HOME `id` \\ c\nlinha"
        ficheiro = Path(self.pasta.name) / "x.env"
        ficheiro.write_bytes(segredos.conteudo({"KAMBA_SECRET_COM_INTERNAL_TOKEN": valor}).encode())
        lancador = (RAIZ / "infra/compose/lancador/lancador.sh").read_text(encoding="utf-8")
        guiao = lancador.replace(segredos.FICHEIRO_NO_CONTENTOR, str(ficheiro))
        saida = subprocess.run(
            ["sh", "-c", guiao, "lancador", "sh", "-c", 'printf %s "$KAMBA_SECRET_COM_INTERNAL_TOKEN"'],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertEqual(saida, valor)

    @unittest.skipUnless(shutil.which("sh") and os.name == "posix", "precisa de sh")
    def test_sem_ficheiro_o_lancador_nao_corre_o_comando(self) -> None:
        lancador = (RAIZ / "infra/compose/lancador/lancador.sh").read_text(encoding="utf-8")
        guiao = lancador.replace(segredos.FICHEIRO_NO_CONTENTOR, "/nao/existe.env")
        corrida = subprocess.run(
            ["sh", "-c", guiao, "lancador", "echo", "correu"], capture_output=True, text=True
        )
        self.assertNotEqual(corrida.returncode, 0)
        self.assertNotIn("correu", corrida.stdout)


class TestComposeReal(unittest.TestCase):
    """A forma que o ensaio mede, sobre o `docker-compose.prod.yml` versionado."""

    def setUp(self) -> None:
        from supply_chain import compose as compose_mod

        self.compose = compose_mod.ler(RAIZ / inspeccao.PROD, RAIZ)
        self.declarados = segredos.declarados(RAIZ)

    def _montagens(self, chaves: dict) -> dict[str, str]:
        """`target -> source` das montagens em forma longa do servico."""
        documento = self.compose.documento
        no = chaves.get("volumes")
        resultado: dict[str, str] = {}
        if no is None:
            return resultado
        for item in documento.resolver(no).filhos:
            item = documento.resolver(item)
            if not item.filhos:
                continue
            mapa = documento.mapa(item)
            resultado[documento.resolver(mapa["target"]).texto()] = (
                documento.resolver(mapa["source"]).texto()
            )
        return resultado

    def test_nenhum_environment_de_prod_leva_um_segredo(self) -> None:
        documento = self.compose.documento
        for servico, (_no, chaves) in self.compose.servicos.items():
            no = chaves.get("environment")
            if no is None:
                continue
            for nome, filho in documento.mapa(documento.resolver(no)).items():
                if nome == "<<":
                    continue
                valor = documento.resolver(filho).texto()
                self.assertIsNone(
                    SEGREDO_NO_AMBIENTE.search(valor), f"{servico}.environment.{nome}"
                )

    def test_quem_tem_segredos_passa_pelo_lancador_e_monta_o_seu_ficheiro(self) -> None:
        self.assertGreaterEqual(len(self.declarados), 19)
        for servico in self.declarados:
            _no, chaves = self.compose.servicos[servico]
            entrypoint = self.compose.documento.itens(chaves["entrypoint"])
            self.assertEqual(entrypoint[:2], ["/bin/sh", segredos.LANCADOR_NO_CONTENTOR], servico)
            montagens = self._montagens(chaves)
            self.assertEqual(
                montagens.get(segredos.LANCADOR_NO_CONTENTOR), "./lancador/lancador.sh", servico
            )
            # O ficheiro **deste** servico, e nao o de outro: cada um so ve os seus.
            self.assertTrue(
                montagens.get(segredos.FICHEIRO_NO_CONTENTOR, "").endswith(f"}}/{servico}.env"),
                servico,
            )

    def test_quem_nao_tem_segredos_nao_tem_lancador(self) -> None:
        for servico, (_no, chaves) in self.compose.servicos.items():
            if servico not in self.declarados:
                self.assertNotIn("entrypoint", chaves, servico)

    def test_o_egress_dez_tem_marcador_para_a_pasta(self) -> None:
        self.assertIn("KAMBA_SEGREDOS_DIR", MARCADORES)

    def test_os_casos_do_canario_sao_servicos_do_compose(self) -> None:
        for servico, linhas, campo, segredo in inspeccao.CASOS_DO_CANARIO:
            self.assertIn(servico, self.compose.servicos)
            self.assertIn(segredo, inspeccao.ids_do_inventario(RAIZ))
            self.assertTrue(any("${KAMBA_SECRET_" in linha for linha in linhas), servico)


if __name__ == "__main__":
    unittest.main()
