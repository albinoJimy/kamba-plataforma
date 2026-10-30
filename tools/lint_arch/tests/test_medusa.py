"""O *lint* do Registo de comercio (KAM-042, criterios 3 e 4): que ele **morde**.

O criterio 3 diz «reprova o CI» e o criterio 4 diz «lint de arquitectura», e e
por isso que isto e um *lint* e nao um teste solto. O que esta bateria prova nao
e que o repositorio esta conforme — isso e uma linha — mas que **um canario
falha**: cada forma de violar a regra, uma a uma, numa arvore temporaria.

A pergunta do KAM-026 e do KAM-027: *o que faria esta bateria passar com o
codigo do lint apagado?* Um `check` que devolvesse sempre `[]` passava o
primeiro teste e falhava os outros doze. Foi por isso que os doze se escreveram.

**E ha uma segunda familia de canarios, que e a que custa mais a escrever:** os
que provam que o *lint* **nao** morde onde nao deve. Nomear uma *flag* EE num
comentario e documentar o controlo, e o `medusa-config.ts` do spike fa-lo de
propriedade. Um *lint* que falhasse por isso proibia documentar a regra — que e
o oposto do que ela serve — e a correccao viria por afrouxar a regra, nao por
melhorar o codigo.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lint_arch import medusa

ROOT = Path(__file__).resolve().parents[3]


class TestRepositorio(unittest.TestCase):
    def test_o_repositorio_esta_conforme(self) -> None:
        self.assertEqual(medusa.check(ROOT), [])

    def test_as_cinco_flags_sao_as_tres_do_criterio_mais_as_duas_da_correccao(
        self,
    ) -> None:
        """As duas a mais sao as do `docs/tecnica/03` §3.4, correccao 3.

        Medidas no KAM-041: o interruptor real sao `MEDUSA_FF_RBAC` e
        `MEDUSA_FF_RBAC_FILTER_FIELDS`, e a segunda «nao esta nomeada em nenhum
        criterio do KAM-041 nem nos criterios de saida do EPIC-04». Nao e um
        limiar novo — e a lacuna que aquela correccao devolveu, implementada.
        """
        self.assertEqual(
            medusa.FLAGS_EE,
            (
                "rbac",
                "auth-oidc",
                "policies",
                "MEDUSA_FF_RBAC",
                "MEDUSA_FF_RBAC_FILTER_FIELDS",
            ),
        )

    def test_o_cabecalho_do_tenant_segue_a_forma_da_casa(self) -> None:
        # Minusculas, como o `x-kamba-interno` do dicionario §3.24 e o
        # `x-kamba-hnd-bot` do §3.32: os cabecalhos ASGI chegam em minusculas, e
        # um `X-Kamba-Tenant` escrito no codigo nunca casava.
        self.assertEqual(medusa.CABECALHO_TENANT, "x-kamba-tenant")
        self.assertEqual(medusa.CABECALHO_TENANT, medusa.CABECALHO_TENANT.lower())

    def test_cada_dispensa_tem_razao_escrita(self) -> None:
        # Uma dispensa sem razao e uma excepcao que ninguem volta a rever.
        self.assertTrue(medusa.DISPENSAS)
        for caminho, razao in medusa.DISPENSAS.items():
            self.assertGreater(len(razao), 30, caminho)


class _ComArvore(unittest.TestCase):
    """Uma arvore temporaria com um repositorio git, porque o lint le o git.

    O `check` varre `git ls-files --cached --others`, e nao `os.walk`: num
    worktree deste repositorio as copias em `.claude/worktrees/*` sao
    repositorios inteiros e o `node_modules` tem milhares de ficheiros com
    `@medusajs` dentro, nenhum deles escrito aqui. Logo um canario precisa de um
    `git init` — os ficheiros ficam por seguir, que e o que `--others` ve.
    """

    def correr(self, ficheiros: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            subprocess.run(
                ["git", "init", "-q"], cwd=raiz, check=True, capture_output=True
            )
            for relativo, conteudo in ficheiros.items():
                destino = raiz / relativo
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_text(conteudo, encoding="utf-8")
            return medusa.check(raiz)


class TestCanariosDoSdk(_ComArvore):
    def test_um_import_do_sdk_fora_do_com_falha(self) -> None:
        for fonte in (
            'import { Modules } from "@medusajs/framework/utils";\n',
            'import "@medusajs/medusa";\n',
            'const m = require("@medusajs/framework");\n',
            'const m = await import("@medusajs/framework");\n',
            'export { x } from "@medusajs/framework/utils";\n',
        ):
            with self.subTest(fonte=fonte):
                achados = self.correr({"services/agr/src/registo.ts": fonte})
                self.assertEqual(len(achados), 1, achados)
                self.assertIn("@medusajs/", achados[0])
                self.assertIn("services/agr/src/registo.ts:1", achados[0])

    def test_o_mesmo_import_dentro_do_com_passa(self) -> None:
        achados = self.correr(
            {
                "services/com/src/adapters/medusa/cliente.ts": (
                    'import { Modules } from "@medusajs/framework/utils";\n'
                )
            }
        )
        self.assertEqual(achados, [])

    def test_o_nome_do_pacote_em_comentario_nao_e_um_import(self) -> None:
        # Este ficheiro de *lint* e o `adapters/medusa/index.ts` escrevem
        # `@medusajs/*` em prosa para explicar a regra. Se a prosa falhasse, a
        # regra nao se podia documentar em sitio nenhum.
        achados = self.correr(
            {
                "services/agr/src/nota.ts": (
                    "// nenhum import de @medusajs/* fora de services/com/\n"
                    "/* nem de @medusajs/framework, por isto. */\n"
                    'export const x = "@medusajs/medusa";\n'
                )
            }
        )
        self.assertEqual(achados, [])

    def test_um_manifesto_que_declara_o_sdk_fora_do_com_falha(self) -> None:
        # Um pacote declarado e um pacote que alguem pode importar amanha sem o
        # gate ver um *import* novo no diff.
        achados = self.correr(
            {
                "services/agr/package.json": (
                    '{"dependencies": {"@medusajs/medusa": "2.21.2"}}\n'
                )
            }
        )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("@medusajs/medusa", achados[0])

    def test_o_manifesto_do_com_pode_declarar_o_sdk(self) -> None:
        achados = self.correr(
            {"services/com/package.json": '{"dependencies": {"@medusajs/medusa": "2.21.2"}}\n'}
        )
        self.assertEqual(achados, [])

    def test_a_arvore_do_spike_esta_dispensada_e_a_razao_esta_escrita(self) -> None:
        achados = self.correr(
            {
                "spikes/medusa-d3/medusa/src/x.ts": (
                    'import { defineConfig } from "@medusajs/framework/utils";\n'
                )
            }
        )
        self.assertEqual(achados, [])
        self.assertIn("spikes/medusa-d3/", medusa.DISPENSAS)


class TestCanariosDaBase(_ComArvore):
    def test_uma_ligacao_a_base_do_registo_fora_do_com_falha(self) -> None:
        achados = self.correr(
            {
                "services/agr/src/kamba_agr/ligacao.py": (
                    'URL = "postgresql://kamba_app@db:5432/kamba_medusa"\n'
                )
            }
        )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("kamba_medusa", achados[0])

    def test_o_comentario_que_explica_a_regra_nao_falha(self) -> None:
        # A `0020` e o `db/tests_agr/test_checkpointer.py` explicam, em
        # comentario, que o Medusa e uma **base** e nao um esquema — e que por
        # isso o mecanismo e o `CONNECT` e nao o `USAGE`. Sao as duas
        # ocorrencias reais fora do COM no repositorio de hoje.
        achados = self.correr(
            {
                "db/migrations/versions/0020_x.py": (
                    "# o Medusa e uma **base** separada (`kamba_medusa`) e o\n"
                    "# bootstrap.py so da CONNECT na base da plataforma.\n"
                    "ESQUEMA = 'lg'\n"
                ),
                "db/tests_agr/test_y.py": (
                    "    # O Medusa e uma base separada (kamba_medusa), nao um\n"
                    "    # esquema, pelo que o mecanismo nao e o USAGE.\n"
                ),
            }
        )
        self.assertEqual(achados, [])

    def test_a_base_dentro_do_com_passa(self) -> None:
        achados = self.correr(
            {"services/com/src/ligacao.ts": 'export const BASE = "kamba_medusa";\n'}
        )
        self.assertEqual(achados, [])


class TestCanariosDasFlagsEE(_ComArvore):
    def test_cada_uma_das_cinco_flags_no_config_falha(self) -> None:
        for flag in medusa.FLAGS_EE:
            with self.subTest(flag=flag):
                achados = self.correr(
                    {
                        "services/com/medusa-config.ts": (
                            "module.exports = defineConfig({\n"
                            f"  featureFlags: {{ {flag}: true }},\n"
                            "});\n"
                        )
                    }
                )
                self.assertTrue(achados, flag)
                self.assertIn(flag, achados[0])
                self.assertIn("Enterprise", achados[0])

    def test_as_flags_num_comentario_do_config_nao_falham(self) -> None:
        """O canario que custa mais, e o que a regra existe para permitir.

        O `spikes/medusa-d3/medusa/medusa-config.ts` nomeia as duas *flags* num
        comentario de cabecalho para documentar o controlo, e o `ee.py` do spike
        salta comentarios pela mesma razao. A arvore do spike esta dispensada,
        mas a propriedade tem de valer tambem para o `medusa-config` do COM no
        dia em que ele existir.
        """
        achados = self.correr(
            {
                "services/com/medusa-config.ts": (
                    "/**\n"
                    " * Nenhuma `featureFlags`. As duas flags EE (`rbac` ->\n"
                    " * `MEDUSA_FF_RBAC`, `rbac_filter_fields` ->\n"
                    " * `MEDUSA_FF_RBAC_FILTER_FIELDS`) tem default_val: false.\n"
                    " * Nem `auth-oidc` nem `policies`.\n"
                    " */\n"
                    "module.exports = defineConfig({ admin: { disable: true } });\n"
                )
            }
        )
        self.assertEqual(achados, [])

    def test_o_numero_da_linha_do_achado_e_o_da_fonte_e_nao_o_da_fonte_limpa(
        self,
    ) -> None:
        # Os comentarios substituem-se por espaco **da mesma altura**, nao se
        # removem: um achado numa linha errada manda quem o le ao sitio errado.
        achados = self.correr(
            {
                "services/com/medusa-config.ts": (
                    "/* uma\n   linha\n   duas\n   tres */\n"
                    "export default { featureFlags: { rbac: true } };\n"
                )
            }
        )
        self.assertTrue(achados)
        self.assertIn("medusa-config.ts:5", achados[0])

    def test_uma_palavra_que_contem_a_flag_nao_e_a_flag(self) -> None:
        # `rbac_legacy` contem `rbac`. Sem a fronteira, um nome qualquer que a
        # contivesse reprovava o CI — e a correccao vinha por apagar o lint.
        achados = self.correr(
            {
                "services/com/medusa-config.ts": (
                    "export default { modules: [{ resolve: './src/modules/rbacoes' }] };\n"
                )
            }
        )
        self.assertEqual(achados, [])

    def test_um_ficheiro_que_nao_e_medusa_config_nao_entra_nesta_regra(self) -> None:
        achados = self.correr(
            {"services/com/src/config.ts": "export default { rbac: true };\n"}
        )
        self.assertEqual(achados, [])


class TestSentinelaDasRotasInternas(_ComArvore):
    def test_uma_rota_interna_do_com_sem_o_cabecalho_falha(self) -> None:
        achados = self.correr(
            {
                "services/com/src/api.ts": (
                    'app.post("/internal/order", (c) => c.json({ ok: true }));\n'
                )
            }
        )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("/internal/order", achados[0])
        self.assertIn(medusa.CABECALHO_TENANT, achados[0])

    def test_a_mesma_rota_com_o_cabecalho_passa(self) -> None:
        achados = self.correr(
            {
                "services/com/src/api.ts": (
                    'const TENANT = "x-kamba-tenant";\n'
                    'app.post("/internal/order", (c) => {\n'
                    "  const t = c.req.header(TENANT);\n"
                    '  if (!t) return c.json({ error: "tenant" }, 400);\n'
                    "  return c.json({ ok: true });\n"
                    "});\n"
                )
            }
        )
        self.assertEqual(achados, [])

    def test_uma_rota_interna_de_outro_servico_nao_entra_nesta_regra(self) -> None:
        # A sentinela e sobre a API interna **do COM**. O `/internal/turn` e o
        # `/internal/resume` do AGR tem as suas credenciais no dicionario §3.24
        # e §3.32, e nao e este lint que as impoe.
        achados = self.correr(
            {"services/agr/src/api_interna.py": 'ROTA = "/internal/turn"\n'}
        )
        self.assertEqual(achados, [])

    def test_a_rota_num_teste_do_com_nao_dispara_a_sentinela(self) -> None:
        achados = self.correr(
            {"services/com/tests/api.test.ts": 'const r = "/internal/order";\n'}
        )
        self.assertEqual(achados, [])


if __name__ == "__main__":
    unittest.main()
