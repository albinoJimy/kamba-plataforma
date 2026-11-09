"""A ligacao dos passos do ensaio, contra um Docker roteirizado (KAM-085).

O que estes ensaios medem e a **ordem e a forma** dos comandos — que o primario
morre antes de o host novo existir, que o repositorio se monta so de leitura no
restauro, que no cenario C o host nasce sem a passphrase e que ela chega pelo
`conf.d` que o `restore_command` tambem le. **Nao** medem o pgBackRest nem o
PostgreSQL: esses mediram-se a correr (`docs/evidencia/KAM-085.md`), e um
Docker falso que respondesse «restaurado» provaria apenas que o falso responde.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from dr_simulacro import ensaio

RAIZ = Path(__file__).resolve().parents[3]

CONFIRMADOS = "".join(f"{n},2026-11-08T10:00:{n:02d}.000000Z\n" for n in range(1, 31))
RESTAURADOS = "".join(f"{n},2026-11-08T10:00:{n:02d}.000000Z\n" for n in range(1, 25))


class DockerRoteirizado:
    def __init__(self):
        self.chamadas: list[list[str]] = []

    def __call__(self, argv, input=None, **_):
        argumentos = argv[1:]
        self.chamadas.append(argumentos)
        texto = " ".join(argumentos)
        saida = ""
        if argumentos[0] == "exec" and "psql" in argumentos and input is not None:
            if "SELECT datname" in input:
                saida = "kamba_platform\nkamba_chatwoot\n"
            elif "query_to_xml" in input:
                saida = "platform.audit_log|1201\ndr_simulacro.marcador|30\n"
            elif "COPY (SELECT seq" in input:
                saida = RESTAURADOS
        elif "pg_is_in_recovery" in texto:
            saida = "f\n"
        elif "SELECT 1" in texto:
            saida = "1\n"
        elif "du -sb" in texto:
            saida = "21474836480\t/x\n"
        elif "auditoria.py verificar" in texto:
            saida = "auditoria: cadeia intacta\n"
        elif "KAMBA_SECRET_" in texto and "gpg" in texto:
            saida = "9\n"
        return subprocess.CompletedProcess(argv, 0, saida, "")

    def indice(self, predicado) -> int:
        for i, argumentos in enumerate(self.chamadas):
            if predicado(argumentos):
                return i
        raise AssertionError("chamada nao encontrada")


def _ensaio(pasta: Path) -> tuple[ensaio.Ensaio, DockerRoteirizado]:
    falso = DockerRoteirizado()
    e = ensaio.Ensaio(RAIZ, pasta, docker=ensaio.Docker({}, correr=falso), dormir=lambda _s: None)
    (pasta / "A").mkdir()
    (pasta / "A" / "confirmados.csv").write_text(CONFIRMADOS, encoding="utf-8")
    return e, falso


class TestCenarioA(unittest.TestCase):
    def test_a_ordem_dos_passos_e_o_que_sai(self):
        with tempfile.TemporaryDirectory() as pasta:
            e, falso = _ensaio(Path(pasta))
            r = ensaio.cenario_a(e, segundos_de_escrita=0)
        self.assertEqual([p["passo"] for p in r["passos"]],
                         ["deteccao", "decisao", "iac", "restauro", "replay", "verificacao", "dns",
                          "iac_emulado"])
        # O contentor do ensaio cronometra-se e fica fora do RTO: o `iac` e
        # orcamento (30 min) no composto, nunca os segundos da emulacao.
        self.assertIsNone(r["passos"][2]["segundos"])
        self.assertGreaterEqual(r["rto_composto_min"] - r["rto_medido_min"], 10 + 10 + 30)
        self.assertEqual(r["rpo"]["perdidos"], 6)
        self.assertEqual(r["rpo"]["segundos"], 6)
        self.assertEqual(r["contagens_divergentes"], {})
        self.assertEqual(r["cadeia"]["codigo"], 0)
        self.assertTrue(r["sossego"]["sossegado"])
        morte = falso.indice(lambda a: a[:2] == ["kill", ensaio.PRIMARIO_A])
        disco = falso.indice(lambda a: a[:3] == ["volume", "rm", "-f"]
                             and a[3] == f"{ensaio.PRIMARIO_A}-dados")
        novo = falso.indice(lambda a: a[0] == "run" and "kam085-restauro-a" in a)
        restauro = falso.indice(lambda a: a[0] == "exec" and "restore" in a)
        self.assertLess(morte, disco)
        self.assertLess(disco, novo)
        self.assertLess(novo, restauro)

    def test_o_restauro_monta_o_repositorio_so_de_leitura_e_com_init(self):
        with tempfile.TemporaryDirectory() as pasta:
            e, falso = _ensaio(Path(pasta))
            ensaio.cenario_a(e, segundos_de_escrita=0)
        run = falso.chamadas[falso.indice(lambda a: a[0] == "run" and "kam085-restauro-a" in a)]
        self.assertIn(f"{ensaio.REPO_A}:{ensaio.REPO_NO_CONTENTOR}:ro", run)
        self.assertIn("--init", run)
        self.assertIn("PGBACKREST_REPO1_CIPHER_PASS", run)

    def test_as_contagens_que_mudam_aparecem(self):
        with tempfile.TemporaryDirectory() as pasta:
            e, falso = _ensaio(Path(pasta))
            original = falso.__call__
            vezes = {"n": 0}

            def com_uma_a_menos(argv, input=None, **k):
                r = original(argv, input=input, **k)
                if input and "query_to_xml" in input:
                    vezes["n"] += 1
                    if vezes["n"] > 2:  # as do host restaurado
                        r = subprocess.CompletedProcess(argv, 0, r.stdout.replace("1201", "1200"), "")
                return r

            e.docker = ensaio.Docker({}, correr=com_uma_a_menos)
            r = ensaio.cenario_a(e, segundos_de_escrita=0)
        self.assertEqual(r["contagens_divergentes"],
                         {"kamba_platform:platform.audit_log": {"antes": 1201, "depois": 1200},
                          "kamba_chatwoot:platform.audit_log": {"antes": 1201, "depois": 1200}})


class TestCenarioC(unittest.TestCase):
    def test_o_host_nasce_sem_a_passphrase_e_ela_chega_pelo_conf_d(self):
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            e, falso = _ensaio(pasta)
            ensaio.cenario_a(e, segundos_de_escrita=0)
            (pasta / "preparar.json").write_text(json.dumps(
                {"exportacao": {"ficheiro": "x.json.gpg", "segredos": 9}}), encoding="utf-8")
            r = ensaio.cenario_c(e)
        self.assertIn("cofre", [p["passo"] for p in r["passos"]])
        run = falso.chamadas[falso.indice(lambda a: a[0] == "run" and "kam085-restauro-c" in a)]
        self.assertNotIn("PGBACKREST_REPO1_CIPHER_PASS", run)
        cofre = falso.indice(lambda a: "gpg" in " ".join(a) and "kam085-restauro-c" in a)
        self.assertIn("/etc/pgbackrest/conf.d/cifra.conf", " ".join(falso.chamadas[cofre]))
        restauro = falso.indice(lambda a: "kam085-restauro-c" in a and "restore" in a)
        apagar = falso.indice(lambda a: a[-1] == "/etc/pgbackrest/conf.d/cifra.conf"
                              and "rm" in a)
        self.assertLess(cofre, restauro)
        self.assertLess(restauro, apagar)
        self.assertEqual(r["contagem_da_exportacao"], 9)

    def test_exportacao_incompleta_falha_alto(self):
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            e, _ = _ensaio(pasta)
            ensaio.cenario_a(e, segundos_de_escrita=0)
            (pasta / "preparar.json").write_text(json.dumps(
                {"exportacao": {"ficheiro": "x.json.gpg", "segredos": 10}}), encoding="utf-8")
            with self.assertRaisesRegex(ensaio.EnsaioFalhou, "exportacao incompleta"):
                ensaio.cenario_c(e)


if __name__ == "__main__":
    unittest.main()
