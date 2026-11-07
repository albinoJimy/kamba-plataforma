"""A recolha, e os canários das três regras que a tornam mais do que um `cat`.

Cada recolha tem uma regra; cada regra tem aqui um caso que a mede nos dois
sentidos. Sem o par, uma verificação que recusasse tudo e uma que aceitasse tudo
dariam ambas verde.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gate_fase0 import recolha


def _raiz() -> Path:
    actual = Path(__file__).resolve().parent
    for candidato in [actual, *actual.parents]:
        if (candidato / "pnpm-workspace.yaml").is_file():
            return candidato
    raise AssertionError("não encontrei a raiz do repositório")


RAIZ = _raiz()


def _json(pasta: Path, nome: str, documento: object) -> Path:
    caminho = pasta / nome
    caminho.write_bytes(json.dumps(documento, ensure_ascii=False).encode("utf-8"))
    return caminho


CORRIDA = {
    "headSha": "fe40048da48fdd003064380944a841cd64de811c",
    "url": "https://github.com/albinoJimy/kamba-plataforma/actions/runs/1",
    "conclusion": "success",
    "jobs": [
        {"name": "gate 1 — build", "conclusion": "success"},
        {"name": "gate 3b — nomes canonicos", "conclusion": "success"},
        {"name": "gate 3c — coerencia do backlog", "conclusion": "success"},
        {"name": "gate 5 — reservado (nao bloqueia) (5, KAM-003)", "conclusion": "failure"},
        {"name": "gates do KAM-002", "conclusion": "success"},
        {"name": "vigia — prova nocturna (nao bloqueia)", "conclusion": "failure"},
    ],
}


class TestOEstadoDosGates(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = TemporaryDirectory()
        self.raiz = Path(self.pasta.name)
        self.addCleanup(self.pasta.cleanup)

    def test_le_o_numero_do_gate_do_nome_do_job(self) -> None:
        self.assertEqual(recolha._gate_do_job("gate 1 — build"), "1")
        self.assertEqual(recolha._gate_do_job("gate 3b — nomes canonicos"), "3b")
        self.assertEqual(recolha._gate_do_job("gate 3c — coerencia do backlog"), "3c")
        self.assertEqual(recolha._gate_do_job("gate 11 — SCA, licencas e SBOM"), "11")

    def test_um_job_que_nao_e_gate_nao_entra(self) -> None:
        """O `gates do KAM-002` é o agregador, e não é um gate do §4."""
        self.assertIsNone(recolha._gate_do_job("gates do KAM-002"))
        self.assertIsNone(recolha._gate_do_job("vigia — prova nocturna (nao bloqueia)"))

    def test_um_gate_sem_job_e_a_terceira_coisa_e_nao_um_vermelho(self) -> None:
        """É a distinção que o parêntesis do critério G0-4 obriga a fazer.

        «os que existem na Fase 0»: um gate do §4 sem *job* nenhum não é verde nem
        vermelho, e contá-lo como qualquer dos dois é a leitura errada — a
        primeira dá cobertura que não existe, a segunda dá um PR travado por um
        gate que ninguém escreveu.
        """
        caminho = _json(self.raiz, "corrida.json", CORRIDA)
        estados, _ = recolha.ler_corrida(caminho)
        por_gate = {estado.gate: estado for estado in estados}
        self.assertEqual(por_gate["10"].estado, "sem job")
        self.assertIsNone(por_gate["10"].job)
        self.assertEqual(por_gate["1"].estado, "verde")

    def test_um_job_que_nao_bloqueia_e_dito(self) -> None:
        """O gate 5 falha **por desenho** até o KAM-003 o ligar.

        `tools/ci_gate_reservado.py` escreve-o: um *job* que passasse por ainda
        não haver nada para testar fazia o *pipeline* parecer que cobre o que não
        cobre. O vermelho tem o ticket no nome e não bloqueia, e a recolha tem de
        dizer as duas coisas — senão lê-se como um gate avariado.
        """
        caminho = _json(self.raiz, "corrida.json", CORRIDA)
        estados, _ = recolha.ler_corrida(caminho)
        gate5 = next(estado for estado in estados if estado.gate == "5")
        self.assertEqual(gate5.estado, "vermelho (failure)")
        self.assertFalse(gate5.bloqueia)

    def test_um_job_normal_bloqueia(self) -> None:
        caminho = _json(self.raiz, "corrida.json", CORRIDA)
        estados, _ = recolha.ler_corrida(caminho)
        gate1 = next(estado for estado in estados if estado.gate == "1")
        self.assertTrue(gate1.bloqueia)

    def test_a_tabela_nomeia_a_execucao_que_a_produziu(self) -> None:
        """Uma tabela sem a corrida é uma tabela que ninguém pode reproduzir."""
        caminho = _json(self.raiz, "corrida.json", CORRIDA)
        estados, meta = recolha.ler_corrida(caminho)
        tabela = recolha.tabela_de_ci(estados, meta)
        self.assertIn("actions/runs/1", tabela)
        self.assertIn("fe40048", tabela)
        # A *fixture* tem três *jobs* de gate; os outros onze do §4 não têm
        # nenhum, e a conta tem de dizer os três números e não só os verdes.
        self.assertIn("3 verde(s), 1 vermelho(s) e 11 sem job", tabela)

    def test_um_ficheiro_sem_jobs_falha(self) -> None:
        caminho = _json(self.raiz, "vazio.json", {"headSha": "abc"})
        with self.assertRaises(recolha.RecolhaInvalida) as apanhado:
            recolha.ler_corrida(caminho)
        self.assertIn("jobs", str(apanhado.exception))

    def test_os_quinze_gates_do_paragrafo_4_estao_todos_na_tabela(self) -> None:
        caminho = _json(self.raiz, "corrida.json", CORRIDA)
        estados, _ = recolha.ler_corrida(caminho)
        self.assertEqual(
            tuple(estado.gate for estado in estados), recolha.GATES_DO_PARAGRAFO_4
        )
        for estado in estados:
            self.assertIn(estado.gate, recolha.NOMES)


REUSO = {
    "vertical": "servicos",
    "reuso_pct": 88.3,
    "loc_especifico": 1705,
    "loc_partilhado": 12869,
    "loc_total": 14574,
    "proveniencia": {"commit": "fe40048da48fdd003064380944a841cd64de811c", "arvore_suja": False},
}


class TestAProveniencia(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = TemporaryDirectory()
        self.raiz = Path(self.pasta.name)
        self.addCleanup(self.pasta.cleanup)

    def test_um_artefacto_limpo_e_da_ponta_certa_passa(self) -> None:
        caminho = _json(self.raiz, "reuso.json", REUSO)
        documento = recolha.ler_reuso(caminho, "fe40048")
        self.assertEqual(documento["reuso_pct"], 88.3)

    def test_um_artefacto_de_arvore_suja_e_recusado(self) -> None:
        """Um número medido numa árvore suja não é o número do ramo.

        E lê-se igualmente verdadeiro, que é o que o torna perigoso.
        """
        sujo = json.loads(json.dumps(REUSO))
        sujo["proveniencia"]["arvore_suja"] = True
        caminho = _json(self.raiz, "sujo.json", sujo)
        with self.assertRaises(recolha.RecolhaInvalida) as apanhado:
            recolha.ler_reuso(caminho)
        self.assertIn("suja", str(apanhado.exception))

    def test_um_artefacto_de_outra_ponta_e_recusado(self) -> None:
        caminho = _json(self.raiz, "reuso.json", REUSO)
        with self.assertRaises(recolha.RecolhaInvalida) as apanhado:
            recolha.ler_reuso(caminho, "deadbee")
        self.assertIn("deadbee", str(apanhado.exception))

    def test_um_artefacto_sem_percentagem_e_recusado(self) -> None:
        sem = {k: v for k, v in REUSO.items() if k != "reuso_pct"}
        caminho = _json(self.raiz, "sem.json", sem)
        with self.assertRaises(recolha.RecolhaInvalida) as apanhado:
            recolha.ler_reuso(caminho)
        self.assertIn("reuso_pct", str(apanhado.exception))

    def test_o_limiar_le_se_do_ficheiro_do_adr_012(self) -> None:
        """70 não se escreve aqui: lê-se de `ci/regra-de-dois.yaml`."""
        self.assertEqual(recolha.limiar_do_reuso(RAIZ), 70.0)

    def test_a_tabela_diz_se_passa_e_onde_foi_medido(self) -> None:
        tabela = recolha.tabela_de_reuso(REUSO, 70.0)
        self.assertIn("88.30%", tabela)
        self.assertIn("fe40048", tabela)
        self.assertIn("Passa o limiar: sim", tabela)

    def test_a_tabela_diz_quando_nao_passa(self) -> None:
        baixo = dict(REUSO, reuso_pct=69.9)
        self.assertIn("Passa o limiar: NÃO", recolha.tabela_de_reuso(baixo, 70.0))


class TestOManifestoDasDecisoes(unittest.TestCase):
    def test_o_manifesto_do_repositorio_passa_as_tres_invariantes(self) -> None:
        linhas, achados = recolha.ler_decisoes(RAIZ)
        self.assertEqual(achados, [])
        self.assertEqual(len(linhas), 7)

    def test_as_sete_linhas_do_criterio_estao_todas(self) -> None:
        """O critério G0-7 nomeia sete: H3, H4, D3, D4, D5, D1 e o parecer P0."""
        linhas, _ = recolha.ler_decisoes(RAIZ)
        self.assertEqual(
            [linha.id for linha in linhas], ["H3", "H4", "D3", "D4", "D5", "D1", "P0"]
        )

    def test_nenhuma_linha_esta_confirmada_e_isso_e_o_resultado(self) -> None:
        """A leitura de 2026-11-06: sete tickets fundidos, zero `confirmada`.

        Prende o número para que ninguém o leia como «ainda não medimos»: foi
        medido, e o resultado é este.
        """
        linhas, _ = recolha.ler_decisoes(RAIZ)
        self.assertEqual([linha.estado for linha in linhas], ["inconclusiva"] * 7)

    def test_cada_ponteiro_existe_na_arvore(self) -> None:
        linhas, _ = recolha.ler_decisoes(RAIZ)
        for linha in linhas:
            self.assertTrue((RAIZ / linha.onde).is_file(), linha.onde)

    def test_um_ponteiro_quebrado_e_achado(self) -> None:
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "d.yaml"
            caminho.write_bytes(_manifesto(onde="docs/nao-existe.md").encode("utf-8"))
            _, achados = recolha.ler_decisoes(RAIZ, caminho)
        self.assertTrue(any("não existe na árvore" in a for a in achados))

    def test_confirmada_sem_evidencia_e_achado(self) -> None:
        """É a regra desta casa, mecanizada: nenhuma caixa sem evidência nomeada."""
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "d.yaml"
            caminho.write_bytes(
                _manifesto(estado="confirmada", evidencia="").encode("utf-8")
            )
            _, achados = recolha.ler_decisoes(RAIZ, caminho)
        self.assertTrue(any("evidência vazia" in a for a in achados))

    def test_linha_sem_credor_e_achado(self) -> None:
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "d.yaml"
            caminho.write_bytes(_manifesto(credor="").encode("utf-8"))
            _, achados = recolha.ler_decisoes(RAIZ, caminho)
        self.assertTrue(any("sem credor" in a for a in achados))

    def test_inconclusiva_sem_plano_e_achado(self) -> None:
        """O critério pede «`inconclusiva` **com plano**», e é a metade que escapa."""
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "d.yaml"
            caminho.write_bytes(_manifesto(plano="").encode("utf-8"))
            _, achados = recolha.ler_decisoes(RAIZ, caminho)
        self.assertTrue(any("sem plano nem pivô" in a for a in achados))

    def test_um_quarto_estado_e_achado(self) -> None:
        """Três estados é a letra do critério; um quarto era inventar resultado."""
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "d.yaml"
            caminho.write_bytes(_manifesto(estado="por decidir").encode("utf-8"))
            _, achados = recolha.ler_decisoes(RAIZ, caminho)
        self.assertTrue(any("não é um dos três" in a for a in achados))

    def test_um_manifesto_conforme_nao_da_achado_nenhum(self) -> None:
        """O par positivo: sem ele, uma verificação que recusasse tudo passava."""
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "d.yaml"
            caminho.write_bytes(_manifesto().encode("utf-8"))
            _, achados = recolha.ler_decisoes(RAIZ, caminho)
        self.assertEqual(achados, [])

    def test_um_manifesto_sem_linhas_e_erro_e_nao_achado(self) -> None:
        """Código 2 e não 1, e a distinção é a do `cli.py`.

        Um manifesto sem linhas não é «o G0-7 não tem decisões»: é uma
        configuração que não se consegue ler, e as duas conclusões são opostas.
        Quem o recusa é o `tools/kamba_yaml.py`, a montante.
        """
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "d.yaml"
            caminho.write_bytes(
                b'version: 1\nlida_em: "2026-11-06"\nponta: "fe40048"\nlinhas:\n'
            )
            with self.assertRaises(ValueError):
                recolha.ler_decisoes(RAIZ, caminho)

    def test_um_manifesto_sem_a_chave_linhas_e_recusado(self) -> None:
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "d.yaml"
            caminho.write_bytes(
                b'version: 1\nlida_em: "2026-11-06"\nponta: "fe40048"\n'
            )
            with self.assertRaises(ValueError):
                recolha.ler_decisoes(RAIZ, caminho)

    def test_a_tabela_leva_o_prefixo_para_a_ligacao_resolver(self) -> None:
        """A tabela do documento é **esta** tabela, não uma cópia corrigida à mão.

        E o prefixo verifica-se **a resolver o caminho**, não a procurar o texto:
        a primeira versão usava três níveis e passava, apesar de três níveis a
        partir de `docs/tecnica/evidencia/validacao/` darem uma ligação quebrada.
        """
        prefixo = "../../../../"
        linhas, _ = recolha.ler_decisoes(RAIZ)
        tabela = recolha.tabela_de_decisoes(linhas, prefixo)
        self.assertIn(f"({prefixo}docs/tecnica/evidencia/validacao/", tabela)
        documento = RAIZ / "docs/tecnica/evidencia/validacao"
        for linha in linhas:
            with self.subTest(linha=linha.id):
                self.assertTrue((documento / (prefixo + linha.onde)).resolve().is_file())

    def test_a_tabela_sem_prefixo_e_relativa_a_raiz(self) -> None:
        linhas, _ = recolha.ler_decisoes(RAIZ)
        tabela = recolha.tabela_de_decisoes(linhas)
        self.assertIn("(docs/tecnica/evidencia/validacao/", tabela)


def _manifesto(
    *,
    onde: str = "docs/logs.md",
    estado: str = "inconclusiva",
    evidencia: str = "medido em fe40048",
    credor: str = "fundador",
    plano: str = "a via está escrita",
) -> str:
    """Um manifesto de uma linha, para os canários.

    Escreve-se aqui em vez de se copiar o do repositório: um canário que mexa no
    ficheiro a sério deixa-o alterado se o ensaio falhar a meio.
    """
    return (
        "version: 1\n"
        'lida_em: "2026-11-06"\n'
        'ponta: "fe40048"\n'
        "linhas:\n"
        '  - id: "X1"\n'
        '    assunto: "um assunto"\n'
        "    tickets:\n"
        '      - "KAM-108"\n'
        f'    onde: "{onde}"\n'
        '    seccao: "§1"\n'
        f'    estado: "{estado}"\n'
        f'    plano_ou_pivo: "{plano}"\n'
        f'    evidencia: "{evidencia}"\n'
        f'    credor: "{credor}"\n'
    )


if __name__ == "__main__":
    unittest.main()
