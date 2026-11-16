"""O `compose_prod` sobre a arvore real, e o que ele recusa (KAM-076).

A pergunta que estes testes respondem e a do KAM-026/KAM-027: *o que faria esta
bateria passar com o codigo do lint apagado?* Um `varrer` que devolvesse sempre
`[]` passava o primeiro teste e falhava todos os outros — e e por isso que os
outros existem.

A prova de que cada **regra** morde nao esta aqui: esta no canario, por mutacao
da arvore real (`tools/compose_prod/canario.py`), e o `test_canario.py` ao lado
corre-o. Aqui ficam as propriedades do conjunto e as recusas de configuracao.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from compose_prod import canario, cli, envoy, lint
from compose_prod.egress_dez import DESTINOS

RAIZ = Path(__file__).resolve().parents[3]


def _copia() -> tuple[tempfile.TemporaryDirectory, Path]:
    pasta = tempfile.TemporaryDirectory(prefix="compose-prod-teste-")
    destino = Path(pasta.name)
    canario._copiar(RAIZ, destino)
    return pasta, destino


class TestArvoreReal(unittest.TestCase):
    def test_o_compose_de_producao_esta_conforme(self) -> None:
        achados, _ = lint.varrer(RAIZ)
        self.assertEqual([str(a) for a in achados], [])

    def test_leu_o_conjunto_todo_e_nao_um_ficheiro_vazio(self) -> None:
        """Um verde sobre zero servicos nao e um verde."""
        _, numeros = lint.varrer(RAIZ)
        self.assertGreaterEqual(numeros["servicos"], 13)
        self.assertEqual(numeros["presentes"], numeros["servicos"])
        self.assertEqual(numeros["proibidos"], 6, "o criterio 1 nomeia seis servicos")
        self.assertGreater(numeros["pendentes"], 0)
        self.assertEqual(numeros["regras"], len(lint.REGRAS))

    def test_os_seis_nomes_proibidos_sao_os_do_criterio_1(self) -> None:
        dados = lint.ler(RAIZ)
        self.assertEqual(
            sorted(dados.proibidos),
            ["langfuse", "minio", "n8n", "nominatim", "storefront", "typebot"],
        )

    def test_as_quatro_redes_e_so_a_edge_tem_rota(self) -> None:
        self.assertEqual(
            lint.REDES, {"edge": False, "app": True, "data": True, "ops": True}
        )

    def test_a_soma_dos_limites_reconcilia_com_o_bloco_e_com_o_kam_187(self) -> None:
        """O bloco propoe limites que somam ~23,5 GB; o KAM-187 soma-lhes 1 088 MiB.

        Nao e um numero inventado aqui: e a soma das onze linhas de limites
        propostos do bloco KAM-076, repartida pelos servicos que o compose tem
        de facto (o Chatwoot em dois contentores, o COM a sair do orcamento do
        Medusa), **mais** o que o KAM-187 acrescentou com a razao escrita.

        **Era `soma == 24064` (23,5 GiB), e mudou com uma razao, nao para o
        ensaio passar.** Os 256 MiB do `worker-canal` saiam da linha «SO e
        proxies», que fechava exacta — e eram de um processo, o `server.ts`, que
        nao consumia nada. O KAM-187 trocou-o pelos quatro processos que fazem
        o trabalho, e a memoria deles **nao sai de nenhuma linha** do bloco: o
        doc 09 §4.2 nao tem linha para o *worker* (o KAM-084 §6.2 chama-lhe
        «linha em falta»). Os quatro somam 1 344 MiB e substituem os 256:

            24 064 - 256 + (2x256 + 2x192 + 2x128 + 192) = 25 152 MiB

        Se a reparticao deixar de fechar, um dos numeros esta errado e vale
        saber qual.
        """
        dados = lint.ler(RAIZ)
        soma = sum(s.memoria_mib for s in dados.manifesto.values())
        do_bloco = 24064
        do_worker_antes = 256
        do_worker_agora = sum(
            dados.manifesto[nome].memoria_mib
            for nome in (
                "worker-canal-entrada",
                "worker-canal-agr-shim",
                "worker-canal-publicador",
                "worker-canal-consumidor",
            )
        )
        self.assertEqual(do_worker_agora, 1344, "2x256 + 2x192 + 2x128 + 192")
        self.assertNotIn("worker-canal", dados.manifesto, "o `server.ts` saiu")
        # KAM-194: as duas pontes e o `idx`, 192 MiB cada, tambem sem linha no
        # bloco — somam-se como os quatro de cima, com a razao no manifesto.
        do_kam_194 = sum(
            dados.manifesto[nome].memoria_mib
            for nome in ("worker-canal-ponte-idx", "worker-canal-ponte-agr", "idx")
        )
        self.assertEqual(do_kam_194, 576, "3x192")
        # KAM-198: o processo de lote do onboarding, 128 MiB, uma replica —
        # tambem sem linha no bloco, pela mesma razao.
        do_kam_198 = dados.manifesto["onboarding-lote"].memoria_mib
        self.assertEqual(do_kam_198, 128)
        self.assertEqual(
            soma, do_bloco - do_worker_antes + do_worker_agora + do_kam_194 + do_kam_198
        )
        self.assertEqual(soma, 25856)

    def test_a_soma_cabe_nos_80_por_cento_da_ram_do_host(self) -> None:
        """Criterio 4: «a soma dos `mem_limit` <= 80% da RAM (<= 25,6 GB)»."""
        dados = lint.ler(RAIZ)
        soma = sum(s.memoria_mib for s in dados.manifesto.values())
        tecto = lint.HOST_RAM_MIB * lint.FRACCAO_MAXIMA_PCT / 100
        self.assertLessEqual(soma, tecto)
        self.assertEqual(tecto, 26214.4, "80% de 32 GiB")

    def test_o_tecto_vem_do_codigo_e_nao_do_manifesto(self) -> None:
        """A prova deixou de ser circular.

        A revisão adversarial mediu que subir `fraccao_maxima_pct` de 80 para
        95, ou `host_ram_mib` de 32768 para 65536, punha o *lint* verde: os dois
        lados da comparação vinham do **mesmo ficheiro** que a regra lê. Hoje o
        tecto está em código e o manifesto tem de concordar com ele.
        """
        self.assertEqual(lint.HOST_RAM_MIB, 32768, "perfil P0 do doc 09 §4.4")
        self.assertEqual(lint.FRACCAO_MAXIMA_PCT, 80, "o critério 4 fixa 80%")
        dados = lint.ler(RAIZ)
        self.assertEqual(dados.host_ram_mib, lint.HOST_RAM_MIB)
        self.assertEqual(dados.fraccao_maxima_pct, lint.FRACCAO_MAXIMA_PCT)

    def test_a_reserva_real_conta_as_replicas(self) -> None:
        """O `mem_limit` é **por contentor**, e o `deploy.replicas` é honrado.

        Este é o teste que faltava quando a revisão adversarial encontrou o
        defeito: a soma contava o total de cada serviço **uma vez**, e o GWY
        reservava 2×512 MiB onde o bloco propõe «2×0,25 GB». Prende-se a
        reconciliação nos três sentidos — o total do manifesto, o total só dos
        presentes, e `mem_limit × replicas` lido do compose.
        """
        dados = lint.ler(RAIZ)
        presentes = {n: s for n, s in dados.manifesto.items() if s.estado == "presente"}

        do_compose = 0
        for nome, (_no, chaves) in dados.prod.servicos.items():
            bruto = lint._valor(dados.prod, chaves, "mem_limit")
            self.assertIsNotNone(bruto, nome)
            por_contentor = lint._memoria_mb(bruto or "")
            self.assertIsNotNone(por_contentor, f"{nome}: {bruto!r}")
            replicas = lint._replicas(dados, chaves)
            do_compose += int(por_contentor or 0) * replicas
            # E cada serviço, um a um: total do manifesto == limite × réplicas.
            self.assertAlmostEqual(
                (por_contentor or 0) * replicas,
                float(presentes[nome].memoria_mib),
                delta=0.5,
                msg=f"{nome}: {bruto} x {replicas} != {presentes[nome].memoria_mib} MiB",
            )

        # **KAM-080: de 14 para 15 presentes, e de 20 736 para 20 992 MiB.** O
        # `alertmanager` estava `pendente` com 256 MiB **ja orcamentados** desde
        # o KAM-076, e passou a `presente`. O que isso move e a reserva **real**
        # — a dos presentes —, e nao o total do manifesto: esse continua nos
        # 24 064 MiB que o teste seguinte prende, porque o manifesto ja contava
        # os pendentes. E a distincao que estes dois numeros existem para
        # mostrar.
        #
        # **KAM-187: de 15 para 18 presentes, e de 20 992 para 22 080 MiB.** O
        # `worker-canal` (256 MiB, o `server.ts`) saiu e entraram os quatro
        # processos (1 344 MiB). Aqui o total do manifesto **muda** — ao
        # contrario do que o KAM-080 fez —, porque nenhum dos quatro estava
        # orcamentado como `pendente`.
        #
        # **KAM-194: de 18 para 21 presentes, e de 22 080 para 22 656 MiB.** As
        # duas pontes e o `idx` (3x192 MiB), uma replica cada; tambem aqui o
        # total do manifesto muda, porque nenhum estava orcamentado.
        #
        # **KAM-198: de 21 para 22 presentes, e de 22 656 para 22 784 MiB.** O
        # processo de lote do onboarding (128 MiB, uma replica), pela mesma razao.
        self.assertEqual(do_compose, 22784, "a reserva real dos 22 presentes, em MiB")
        self.assertEqual(sum(s.memoria_mib for s in presentes.values()), 22784)
        self.assertEqual(len(presentes), 22)
        self.assertLessEqual(do_compose, 26214.4)

    def test_cada_variavel_obrigatoria_tem_marcador(self) -> None:
        """O `egress-dez` levanta o compose de producao, e a interpolacao e do ficheiro.

        Um `${X:?}` novo sem marcador em `egress_dez.MARCADORES` faz o
        `docker compose up proxy-saida` falhar antes de haver contentor — e o
        gate 6 fica vermelho por um servico que nem arranca. Aconteceu duas
        vezes: no PR #125 (KAM-178) e no do KAM-187.
        """
        import re

        texto = (RAIZ / lint.PROD).read_text(encoding="utf-8")
        exigidas = set(re.findall(r"\$\{([A-Za-z0-9_]+):\?", texto))
        from compose_prod import egress_dez

        self.assertEqual(sorted(exigidas - set(egress_dez.MARCADORES)), [])

    def test_o_gwy_e_o_agr_tem_duas_replicas_no_manifesto(self) -> None:
        dados = lint.ler(RAIZ)
        for nome in sorted(lint.DUAS_REPLICAS):
            self.assertEqual(dados.manifesto[nome].replicas, 2, nome)

    def test_a_configuracao_do_proxy_esta_em_dia_face_a_allowlist(self) -> None:
        """O gerado e versionado: divergir e um achado, nao uma surpresa."""
        mudou, caminho = envoy.gerar(RAIZ, escrever=False)
        self.assertFalse(mudou, f"{caminho} desactualizado; corra `compose_prod gerar`")

    def test_o_gerado_tem_cada_fqdn_com_e_sem_porta(self) -> None:
        """O `:authority` de um CONNECT traz a porta e o de um GET nao."""
        texto = (RAIZ / lint.ENVOY).read_text(encoding="utf-8")
        dados = lint.ler(RAIZ)
        for fqdn in dados.allowlist:
            self.assertIn(f'"{fqdn}"', texto)
            self.assertIn(f'"{fqdn}:443"', texto)

    def test_o_gerado_nega_por_omissao_e_registra(self) -> None:
        texto = (RAIZ / lint.ENVOY).read_text(encoding="utf-8")
        self.assertIn('- "*"', texto, "falta o virtual_host que recusa tudo o mais")
        self.assertIn("status: 403", texto)
        self.assertIn("access_log", texto, "sem registo, metade do criterio 3 falta")
        self.assertIn("%REQ(:AUTHORITY)%", texto)
        self.assertNotIn("%REQ(COOKIE)%", texto, "o registo nunca leva conteudo")


class TestGuiaoDosDezDestinos(unittest.TestCase):
    def test_sao_dez(self) -> None:
        self.assertEqual(len(DESTINOS), 10, "o criterio 3 pede dez destinos")

    def test_cada_destino_tem_razao_escrita(self) -> None:
        for destino in DESTINOS:
            self.assertTrue(destino["razao"].strip(), destino["fqdn"])

    def test_o_guiao_concorda_com_a_allowlist(self) -> None:
        """Um guiao que discorde da allowlist afirma o oposto do ficheiro."""
        allowlist = lint.ler(RAIZ).allowlist
        for destino in DESTINOS:
            self.assertEqual(
                destino["permitido"],
                destino["fqdn"] in allowlist,
                f"{destino['fqdn']}: o guiao e a allowlist discordam",
            )

    def test_ha_permitidos_e_recusados(self) -> None:
        """Um guiao so com recusas nao prova que a allowlist deixa passar."""
        permitidos = [d for d in DESTINOS if d["permitido"]]
        self.assertGreaterEqual(len(permitidos), 1)
        self.assertGreaterEqual(len(DESTINOS) - len(permitidos), 1)

    def test_o_facilitador_esta_recusado_e_a_razao_explica(self) -> None:
        """O criterio 3 nomeia-o como permitido; aqui esta recusado.

        Nenhum servico do repositorio o declara (nao ha `services/pay/`, e o
        adaptador e o KAM-056), e um destino na allowlist sem dono e o
        contrario de negar por omissao. O teste prende a **razao escrita**: se
        alguem o abrir, abre-o com dono, e este teste muda com ele.
        """
        facilitador = [d for d in DESTINOS if d["fqdn"] == "api.proxypay.co.ao"]
        self.assertEqual(len(facilitador), 1)
        self.assertFalse(facilitador[0]["permitido"])
        self.assertIn("KAM-056", facilitador[0]["razao"])


class TestConfiguracaoInvalida(unittest.TestCase):
    """Um ficheiro de politica ilegivel e saida 2, nunca um verde."""

    def test_manifesto_ausente(self) -> None:
        pasta, destino = _copia()
        with pasta:
            (destino / lint.MANIFESTO).unlink()
            with self.assertRaises(lint.ConfiguracaoInvalida):
                lint.varrer(destino)

    def test_denylist_vazia_nao_passa(self) -> None:
        """Uma *denylist* vazia passaria sempre, e o criterio 1 nomeia seis."""
        pasta, destino = _copia()
        with pasta:
            caminho = destino / lint.MANIFESTO
            texto = caminho.read_text(encoding="utf-8")
            texto = texto[: texto.index("proibidos:")] + "proibidos: []\n"
            caminho.write_text(texto, encoding="utf-8", newline="\n")
            with self.assertRaises(lint.ConfiguracaoInvalida):
                lint.varrer(destino)

    def test_pendente_sem_ticket_nao_passa(self) -> None:
        pasta, destino = _copia()
        with pasta:
            caminho = destino / lint.MANIFESTO
            texto = caminho.read_text(encoding="utf-8").replace(
                "    estado: pendente\n    ticket: KAM-042\n", "    estado: pendente\n", 1
            )
            caminho.write_text(texto, encoding="utf-8", newline="\n")
            with self.assertRaises(lint.ConfiguracaoInvalida):
                lint.varrer(destino)

    def test_allowlist_que_nao_nega_por_omissao_nao_passa(self) -> None:
        pasta, destino = _copia()
        with pasta:
            caminho = destino / lint.ALLOWLIST
            texto = caminho.read_text(encoding="utf-8").replace(
                "por_omissao: negar", "por_omissao: permitir", 1
            )
            caminho.write_text(texto, encoding="utf-8", newline="\n")
            with self.assertRaises(lint.ConfiguracaoInvalida):
                lint.varrer(destino)

    def test_compose_de_producao_ausente(self) -> None:
        pasta, destino = _copia()
        with pasta:
            (destino / lint.PROD).unlink()
            with self.assertRaises(lint.ConfiguracaoInvalida):
                lint.varrer(destino)


class TestCli(unittest.TestCase):
    def test_lint_sobre_a_arvore_real_sai_zero(self) -> None:
        self.assertEqual(cli.main(["--root", str(RAIZ), "lint"]), 0)

    def test_gerar_verificar_sobre_a_arvore_real_sai_zero(self) -> None:
        self.assertEqual(cli.main(["--root", str(RAIZ), "gerar", "--verificar"]), 0)

    def test_configuracao_invalida_sai_dois_e_nao_um(self) -> None:
        """A distincao importa: 1 e achado, 2 e politica ilegivel."""
        pasta, destino = _copia()
        with pasta:
            (destino / lint.MANIFESTO).unlink()
            self.assertEqual(cli.main(["--root", str(destino), "lint"]), 2)

    def test_achado_sai_um(self) -> None:
        pasta, destino = _copia()
        with pasta:
            copia = canario.Copia(destino)
            copia.trocar(lint.PROD, r"^      replicas: 2$", "      replicas: 1")
            self.assertEqual(cli.main(["--root", str(destino), "lint"]), 1)

    def test_gerar_verificar_apanha_o_gerado_desactualizado(self) -> None:
        pasta, destino = _copia()
        with pasta:
            caminho = destino / lint.ENVOY
            caminho.write_text("# desactualizado\n", encoding="utf-8", newline="\n")
            self.assertEqual(
                cli.main(["--root", str(destino), "gerar", "--verificar"]), 1
            )


if __name__ == "__main__":
    unittest.main()
