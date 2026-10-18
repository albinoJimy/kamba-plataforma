"""O registo de licencas por versao (criterio 6) e o `cosign verify` (criterio 2)."""

from __future__ import annotations

import datetime
import unittest

from supply_chain import cosign, imagens, licencas
from supply_chain.base import ConfiguracaoInvalida

from .base import ComArvore

REGISTO = "ci/supply-chain/licencas.yaml"
INVENTARIO = "ci/supply-chain/imagens.yaml"


class TestRegisto(ComArvore):
    def regras_de(self) -> list[str]:
        return self.regras(licencas.verificar(self.raiz)[0])

    def test_o_minimo_passa(self) -> None:
        achados, resumo = licencas.verificar(self.raiz)
        self.assertEqual([str(a) for a in achados], [])
        self.assertEqual(resumo["componentes"], 12)
        self.assertEqual(resumo["estados"]["pendente_de_decisao"], 2)

    # ------------------------------------------------ contra a politica

    def test_o_estado_tem_de_ser_o_que_a_politica_da(self) -> None:
        for antigo, novo in (
            # Valkey: BSD-3-Clause esta na allowlist, mas a D12 trava-o pelo nome.
            ("    estado: pendente_de_decisao\n    decisao: D12\n    ligacoes", "    estado: permitido\n    ligacoes"),
            ("    estado: pendente_de_decisao\n    decisao: D12\n    ligacoes", "    estado: nao_adoptado\n    ligacoes"),
            # `MIT AND BUSL-1.1`: num AND a pior manda.
            ("    licenca: MIT AND BUSL-1.1\n    data_verificacao: \"2026-10-08\"\n    fonte: \"teste\"\n    estado_verificacao: CONFIRMADO\n    estado: nao_adoptado",
             "    licenca: MIT AND BUSL-1.1\n    data_verificacao: \"2026-10-08\"\n    fonte: \"teste\"\n    estado_verificacao: CONFIRMADO\n    estado: permitido"),
            # Uma licenca que ninguem classificou nao se regista como permitida.
            ("    licenca: PostgreSQL", "    licenca: NOASSERTION"),
            ("    licenca: PostgreSQL", "    licenca: LicenseRef-Qualquer"),
            ("    licenca: PostgreSQL", "    licenca: AGPL-3.0"),
            # Uma permitida nao se regista como pendente nem como excepcao.
            ("    licenca: PostgreSQL\n    data_verificacao: \"2026-10-08\"\n    fonte: \"teste\"\n    estado_verificacao: CONFIRMADO\n    estado: permitido",
             "    licenca: PostgreSQL\n    data_verificacao: \"2026-10-08\"\n    fonte: \"teste\"\n    estado_verificacao: CONFIRMADO\n    estado: pendente_de_decisao\n    decisao: D12"),
        ):
            with self.subTest(novo=novo[-60:]):
                original = self.ler(REGISTO)
                self.trocar(REGISTO, antigo, novo)
                try:
                    regras = self.regras_de()
                finally:
                    self.escrever(REGISTO, original)
                self.assertIn("licenca-estado-incoerente", regras)

    def test_or_com_um_ramo_permitido_passa(self) -> None:
        self.trocar(REGISTO, "    licenca: PostgreSQL", "    licenca: GPL-3.0 OR MIT")
        self.assertEqual(self.regras_de(), [])

    def test_pendente_exige_a_decisao_que_o_trava(self) -> None:
        for novo in ("", "    decisao: D6\n", "    decisao: depois\n"):
            with self.subTest(novo=novo):
                original = self.ler(REGISTO)
                self.trocar(REGISTO, "    decisao: D12\n    ligacoes", novo + "    ligacoes")
                try:
                    self.assertEqual(self.regras_de(), ["licenca-estado-incoerente"])
                finally:
                    self.escrever(REGISTO, original)

    def test_excepcao_exige_adr_e_nota(self) -> None:
        base = "    estado: nao_adoptado\n    ee: \"Os modulos Enterprise Edition sao BUSL-1.1.\""
        nota = "    nota: \"O ADR admite o uso do nucleo MIT sem os modulos Enterprise Edition.\""
        for novo, esperado in (
            ("    estado: excepcao\n    ee: \"Os modulos Enterprise Edition sao BUSL-1.1.\"", ["licenca-sem-excepcao"]),
            (f"    estado: excepcao\n    excepcao_adr: ADR-002\n    ee: \"Os modulos Enterprise Edition sao BUSL-1.1.\"", ["licenca-sem-excepcao"]),
            (f"    estado: excepcao\n    excepcao_adr: \"aprovacao:fundador@2026-10-12\"\n{nota}\n    ee: \"Os modulos Enterprise Edition sao BUSL-1.1.\"", ["licenca-sem-excepcao"]),
            (f"    estado: excepcao\n    excepcao_adr: ADR-002\n{nota}\n    ee: \"Os modulos Enterprise Edition sao BUSL-1.1.\"", []),
        ):
            with self.subTest(novo=novo[:60]):
                original = self.ler(REGISTO)
                self.trocar(REGISTO, base, novo)
                try:
                    self.assertEqual(self.regras_de(), esperado)
                finally:
                    self.escrever(REGISTO, original)

    # ---------------------------------------- contra a lista de bloqueio

    def test_bloqueado_tem_de_estar_na_lista_de_bloqueio(self) -> None:
        self.trocar(REGISTO, "  - componente: minio\n", "  - componente: garage\n")
        self.assertEqual(self.regras_de(), ["bloqueado-fora-da-lista"])

    def test_bloqueado_pela_ligacao(self) -> None:
        self.trocar(REGISTO, "  - componente: minio\n", "  - componente: armazenamento-antigo\n")
        self.assertEqual(self.regras_de(), ["bloqueado-fora-da-lista"])
        self.escrever(REGISTO, self.ler(REGISTO) + "    ligacoes:\n      - \"imagem:minio/minio\"\n")
        self.assertEqual(self.regras_de(), [])

    # ------------------------------------------------ contra o repositorio

    def test_versao_em_uso_diferente_da_lida(self) -> None:
        self.trocar(REGISTO, '    versao: "4.13.13"', '    versao: "4.12.0"')
        achados, _ = licencas.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["licenca-versao-diferente"])
        self.assertIn("4.13.13", achados[0].mensagem)

    def test_subir_o_lockfile_obriga_a_reler(self) -> None:
        self.trocar("pnpm-lock.yaml", "  hono@4.13.13:\n    resolution", "  hono@4.14.0:\n    resolution")
        self.assertEqual(self.regras_de(), ["licenca-versao-diferente"])

    def test_etiqueta_de_imagem_menos_precisa_do_que_a_versao_lida(self) -> None:
        self.trocar(REGISTO, '    versao: "24.21.0"', '    versao: "24.21.0.1"')
        self.assertEqual(self.regras_de(), [])
        self.trocar(REGISTO, '    versao: "24.21.0.1"', '    versao: "24.2"')
        self.assertEqual(self.regras_de(), ["licenca-versao-diferente"])

    def test_nao_adoptado_que_aparece_num_manifesto(self) -> None:
        self.trocar("services/gwy/package.json", '"hono": "4.13.13"', '"hono": "4.13.13", "meilisearch": "^0.50.0"')
        achados, _ = licencas.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["componente-presente-sem-aprovacao"])

    def test_nao_adoptado_que_aparece_como_imagem(self) -> None:
        self.trocar(REGISTO, '      - "npm:meilisearch"', '      - "imagem:meilisearch"')
        self.trocar(INVENTARIO, "  - nome: node\n", "  - nome: getmeili/meilisearch\n")
        self.trocar(REGISTO, '      - "imagem:node"', '      - "imagem:outra"')
        self.assertEqual(self.regras_de(), ["componente-presente-sem-aprovacao"])

    # ----------------------------- achados da revisao adversarial (ANALISE-10)

    def test_excepcao_com_adr_que_nao_existe(self) -> None:
        """M2: um ADR com o numero 999 tem a forma de um ADR e nao e um."""
        self.trocar(
            REGISTO,
            "    estado: nao_adoptado\n    ee: \"Os modulos Enterprise Edition sao BUSL-1.1.\"",
            "    estado: excepcao\n    excepcao_adr: ADR-" + "999" + "\n"
            "    nota: \"O ADR admite o uso do nucleo MIT sem os modulos Enterprise Edition.\"\n"
            "    ee: \"Os modulos Enterprise Edition sao BUSL-1.1.\"",
        )
        achados, _ = licencas.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["licenca-sem-excepcao"])
        self.assertIn("que exista", achados[0].mensagem)

    def test_adr_local_existente_vale(self) -> None:
        self.trocar(
            REGISTO,
            "    estado: nao_adoptado\n    ee: \"Os modulos Enterprise Edition sao BUSL-1.1.\"",
            "    estado: excepcao\n    excepcao_adr: ADR-L001\n"
            "    nota: \"O ADR admite o uso do nucleo MIT sem os modulos Enterprise Edition.\"\n"
            "    ee: \"Os modulos Enterprise Edition sao BUSL-1.1.\"",
        )
        self.assertEqual(self.regras_de(), [])

    def test_componente_obrigatorio_apagado(self) -> None:
        """M7: apagar a linha do Medusa nao apaga a exigencia de a ter."""
        texto = self.ler(REGISTO)
        inicio = texto.index("  - componente: medusa\n")
        fim = texto.index("  - componente: meilisearch\n")
        self.escrever(REGISTO, texto[:inicio] + texto[fim:])
        achados, _ = licencas.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["componente-obrigatorio-em-falta"])
        self.assertIn("`medusa`", achados[0].mensagem)

    def test_os_obrigatorios_incluem_os_da_d12_e_os_de_edicao_enterprise(self) -> None:
        self.assertLessEqual({"redis", "valkey", "medusa", "chatwoot", "meilisearch"}, licencas.OBRIGATORIOS)
        self.assertLessEqual(licencas.COM_EDICAO_ENTERPRISE, licencas.OBRIGATORIOS)

    def test_a_d12_nao_se_contorna_mudando_o_nome(self) -> None:
        """M7: Redis rebaptizado, com licenca permitida, mas ainda ligado a `imagem:redis`."""
        self.trocar(REGISTO, "  - componente: langfuse\n", "  - componente: kv-fila\n")
        self.trocar(REGISTO, '      - "imagem:langfuse"', '      - "imagem:redis"')
        self.trocar(REGISTO, "    estado: nao_adoptado\n    ee: \"As pastas ee/ ficam de fora.\"", "    estado: permitido")
        self.assertIn("licenca-estado-incoerente", self.regras_de())

    def test_nao_adoptado_tem_de_dizer_como_apareceria(self) -> None:
        """M7: sem `ligacoes`, a ausencia de um componente nao se verifica."""
        self.trocar(REGISTO, '    ligacoes:\n      - "npm:meilisearch"\n', "")
        self.assertEqual(self.regras_de(), ["nao-adoptado-sem-ligacoes"])

    def test_pypi_compara_se_normalizado(self) -> None:
        self.trocar(REGISTO, '      - "npm:meilisearch"', '      - "pypi:meili_search"')
        self.maxDiff = None
        self.escrever("services/agr/requirements/runtime.txt", "Meili-Search==1.0.0\n")
        self.assertEqual(self.regras_de(), ["componente-presente-sem-aprovacao"])

    # ------------------------------------------------ contra o inventario

    def test_componente_de_imagem_sem_linha(self) -> None:
        self.trocar(INVENTARIO, "      - postgresql\n", "      - postgresql\n      - postgis\n")
        achados, _ = licencas.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro) for a in achados], [("componente-sem-licenca", INVENTARIO)])

    # ----------------------------------------------- edicao Enterprise

    def test_componentes_com_edicao_enterprise_tem_de_a_registar(self) -> None:
        self.trocar(REGISTO, '    ee: "RBAC e SSO/OIDC sao proprietarios e ficam desligados."\n', "")
        self.assertEqual(self.regras_de(), ["ee-sem-registo"])
        self.trocar(REGISTO, "    estado: permitido\n    ligacoes:\n      - \"npm:@medusajs/medusa\"", "    estado: permitido\n    ee: \"sim\"\n    ligacoes:\n      - \"npm:@medusajs/medusa\"")
        self.assertEqual(self.regras_de(), ["ee-sem-registo"])

    # ------------------------------------------------- erros de forma

    def test_registo_invalido_levanta(self) -> None:
        for antigo, novo, fragmento in (
            ("version: 1", "version: 3", "'version' tem de ser 1"),
            # O fragmento mudou no KAM-134: a implementacao local deste modulo
            # passou a chamar o `kamba_yaml.exigir_chaves` partilhado.
            ("version: 1", "version: 1\nextra: sim", "chave(s) desconhecida(s)"),
            ('    versao: "18.6"\n', "", "campos em falta: versao"),
            ("    licenca: PostgreSQL", "    licenca: PostgreSQL\n    aprovado_por: eu",
             "chave(s) desconhecida(s)"),
            ("  - componente: postgresql", "  - componente: Postgre SQL", "minusculas"),
            ("  - componente: node", "  - componente: postgresql", "repetido"),
            ('    data_verificacao: "2026-10-08"\n    fonte: "teste"\n    estado_verificacao: CONFIRMADO\n    estado: permitido\n  - componente: node',
             '    data_verificacao: "em Outubro"\n    fonte: "teste"\n    estado_verificacao: CONFIRMADO\n    estado: permitido\n  - componente: node', "data ISO"),
            ("    estado: bloqueado", "    estado: tolerado", "`estado` tem de ser um de"),
            ("    estado_verificacao: INDÍCIO", "    estado_verificacao: PROVAVEL", "`estado_verificacao`"),
            ('      - "npm:hono"', '      - "hono"', "ligacao"),
            ('    ligacoes:\n      - "npm:hono"', "    ligacoes: hono", "`ligacoes` tem de ser uma lista"),
        ):
            with self.subTest(fragmento=fragmento, novo=novo[:40]):
                original = self.ler(REGISTO)
                self.trocar(REGISTO, antigo, novo)
                try:
                    with self.assertRaises(ConfiguracaoInvalida) as contexto:
                        licencas.verificar(self.raiz)
                finally:
                    self.escrever(REGISTO, original)
                self.assertIn(fragmento, str(contexto.exception))

    def test_data_futura(self) -> None:
        with self.assertRaises(ConfiguracaoInvalida) as contexto:
            licencas.ler_registo(self.raiz, hoje=datetime.date(2026, 10, 1))
        self.assertIn("futuro", str(contexto.exception))

    def test_ficheiro_em_falta_vazio_ou_ilegivel(self) -> None:
        self.escrever(REGISTO, "version: 1\ncomponentes: []\n")
        with self.assertRaises(ConfiguracaoInvalida):
            licencas.verificar(self.raiz)
        self.escrever(REGISTO, "version: 1\ncomponentes: {a: b}\n")
        with self.assertRaises(ConfiguracaoInvalida):
            licencas.verificar(self.raiz)
        (self.raiz / REGISTO).unlink()
        with self.assertRaises(ConfiguracaoInvalida):
            licencas.verificar(self.raiz)

    def test_politica_ou_lista_de_bloqueio_em_falta(self) -> None:
        for ficheiro in ("ci/licenses.yaml", "tools/blocklist.yaml"):
            with self.subTest(ficheiro=ficheiro):
                original = self.ler(ficheiro)
                (self.raiz / ficheiro).unlink()
                try:
                    with self.assertRaises(ConfiguracaoInvalida):
                        licencas.verificar(self.raiz)
                finally:
                    self.escrever(ficheiro, original)


class TestCosign(ComArvore):
    """A decisao, que e o que se consegue provar sem `cosign` nem registo.

    O executor e injectado: **nenhum destes testes corre o cosign real**, e o
    modulo di-lo no cabecalho.
    """

    def com_litellm(self) -> imagens.Inventario:
        self.trocar(
            INVENTARIO, "fontes_adicionais:",
            "  - nome: ghcr.io/berriai/litellm\n    etiqueta: main-v1.104.2\n"
            f"    digest: \"sha256:{'a' * 64}\"\n    lido_em: \"2026-10-12\"\n    lido_de: teste\n"
            "    componentes:\n      - node\n    cosign: verificar\n"
            "    cosign_identidade: \"https://github.com/BerriAI/litellm/.github/workflows/x.yml@refs/heads/main\"\n"
            "    cosign_emissor: \"https://token.actions.githubusercontent.com\"\n"
            "fontes_adicionais:",
        )
        return imagens.ler_inventario(self.raiz)

    def test_sem_imagens_a_verificar_passa_e_diz_quantas(self) -> None:
        achados, resumo = cosign.verificar(imagens.ler_inventario(self.raiz), tem_binario=lambda: False)
        self.assertEqual(achados, [])
        self.assertEqual(resumo, {"a_verificar": 0, "verificadas": 0})

    def test_imagem_a_verificar_sem_binario_falha(self) -> None:
        achados, resumo = cosign.verificar(self.com_litellm(), tem_binario=lambda: False)
        self.assertEqual(self.regras(achados), ["cosign-sem-binario"])
        self.assertEqual(resumo["verificadas"], 0)

    def test_assinatura_valida_passa(self) -> None:
        chamadas: list[list[str]] = []

        def executor(comando: list[str]) -> tuple[int, str]:
            chamadas.append(comando)
            return 0, "Verification for ghcr.io/berriai/litellm -- ok"

        achados, resumo = cosign.verificar(self.com_litellm(), executor=executor, tem_binario=lambda: True)
        self.assertEqual(achados, [])
        self.assertEqual(resumo, {"a_verificar": 1, "verificadas": 1})
        comando = chamadas[0]
        self.assertEqual(comando[:2], ["cosign", "verify"])
        # Verifica-se o digest, nunca a etiqueta.
        self.assertEqual(comando[-1], f"ghcr.io/berriai/litellm@sha256:{'a' * 64}")
        self.assertNotIn("main-v1.104.2", " ".join(comando))
        self.assertIn("--certificate-identity", comando)
        self.assertIn("--certificate-oidc-issuer", comando)

    def test_imagem_adulterada_falha(self) -> None:
        achados, resumo = cosign.verificar(
            self.com_litellm(),
            executor=lambda _c: (1, "Error: no matching signatures"),
            tem_binario=lambda: True,
        )
        self.assertEqual(self.regras(achados), ["cosign-falhou"])
        self.assertIn("no matching signatures", achados[0].mensagem)
        self.assertEqual(resumo["verificadas"], 0)

    def test_o_executor_real_trata_binario_em_falta_como_falha(self) -> None:
        codigo, _saida = cosign._executar(["binario-que-nao-existe-kamba", "verify"])
        self.assertNotEqual(codigo, 0)

    def test_o_executor_real_devolve_o_codigo_do_processo(self) -> None:
        import sys

        self.assertEqual(cosign._executar([sys.executable, "-c", "raise SystemExit(0)"])[0], 0)
        codigo, saida = cosign._executar([sys.executable, "-c", "import sys; sys.stderr.write('adulterada'); sys.exit(3)"])
        self.assertEqual((codigo, saida), (3, "adulterada"))


if __name__ == "__main__":
    unittest.main()
