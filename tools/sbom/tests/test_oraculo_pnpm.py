"""A travessia contra o **proprio pnpm**, importador a importador.

Porque e que isto existe, e nao basta uma *fixture* nossa: a primeira versao do
KAM-133 foi verificada com *fixtures* escritas por quem escreveu o codigo, e
elas passaram todas enquanto a travessia trazia **14 componentes a mais** a
tres servicos. Uma *fixture* prova que o leitor faz o que o autor pensou; so um
oraculo de fora prova que o que ele pensou e o que o `pnpm` faz.

O oraculo e `tools/sbom/tests/oraculo_pnpm.json`, medido com

    pnpm --filter ./<importador> list --prod --depth Infinity --json

dentro da imagem fixada por *digest* que o `.node-version` e o
`ci/supply-chain/imagens.yaml` nomeiam, e com o `pnpm` do `packageManager`. O
ficheiro guarda o `sha256` do `pnpm-lock.yaml` do dia em que foi medido: se o
*lockfile* mudar e o oraculo nao, **o teste diz que esta velho em vez de
mentir** — que e a diferenca entre um numero fixado e um numero medido.

Compara-se o **fecho de producao** (`apenas_runtime=True`) porque e o unico modo
em que o `pnpm list` e fiavel ponta a ponta: sem `--prod` ele nao desce a arvore
de uma `devDependency` ate ao fim — no `packages/core-ts` mostra o `pg-types` e
nao mostra os cinco filhos dele —, e compara-lo com o fecho completo dava uma
divergencia que e do `pnpm list` e nao nossa.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from sbom import pnpm_lock

ROOT = Path(__file__).resolve().parents[3]
ORACULO = Path(__file__).resolve().parent / "oraculo_pnpm.json"


class TestOraculoPnpm(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dados = json.loads(ORACULO.read_text(encoding="utf-8"))
        cls.grafo = pnpm_lock.ler(ROOT / "pnpm-lock.yaml")

    def test_o_oraculo_e_do_lockfile_de_hoje(self) -> None:
        """Um oraculo velho e pior do que nenhum: passa a abencoar o erro."""
        actual = hashlib.sha256((ROOT / "pnpm-lock.yaml").read_bytes()).hexdigest()
        self.assertEqual(
            actual,
            self.dados["_lockfile_sha256"],
            "o pnpm-lock.yaml mudou desde que o oraculo foi medido. Volte a "
            f"medi-lo com `{self.dados['_comando']}` na imagem "
            f"{self.dados['_imagem']} e actualize {ORACULO.name}.",
        )

    def test_o_fecho_de_producao_e_o_que_o_pnpm_diz(self) -> None:
        for importador, esperado in self.dados["fecho_de_producao"].items():
            with self.subTest(importador=importador):
                obtido = pnpm_lock.fecho(
                    importador, self.grafo, apenas_runtime=True
                ).terceiros
                self.assertEqual(
                    sorted(obtido),
                    sorted(esperado),
                    f"{importador}: a mais {sorted(set(obtido) - set(esperado))}, "
                    f"a menos {sorted(set(esperado) - set(obtido))}",
                )

    def test_o_pg_nao_chega_aos_tres_servicos_que_o_nao_tem(self) -> None:
        """O defeito que a revisao adversarial encontrou, fixado pelo nome.

        O `pg` esta resolvido no *snapshot* do `bullmq` como *peer* opcional,
        e esta resolvido porque o `@kamba/core-ts` o declara nas suas
        `devDependencies`. Segui-lo trazia o `pg` e mais treze ao `gwy`, ao
        `com` e ao `onboarding-web` — o grupo excluido um nivel acima a voltar
        a entrar um nivel abaixo.
        """
        arrastados = {
            "pg", "pg-cloudflare", "pg-connection-string", "pg-int8", "pg-pool",
            "pg-protocol", "pg-types", "pgpass", "postgres-array",
            "postgres-bytea", "postgres-date", "postgres-interval", "split2",
            "xtend",
        }
        self.assertEqual(len(arrastados), 14)
        for servico in ("services/gwy", "services/com", "services/onboarding-web"):
            with self.subTest(servico=servico):
                nomes = {
                    x.rsplit("@", 1)[0]
                    for x in pnpm_lock.fecho(servico, self.grafo).terceiros
                }
                self.assertEqual(nomes & arrastados, set(), sorted(nomes & arrastados))

    def test_o_ioredis_continua_la_e_pela_razao_certa(self) -> None:
        """A regra tem de cortar o `pg` sem cortar o `ioredis`.

        Os dois sao *peer* opcional do `bullmq` e resolvem-se da mesma maneira
        no *snapshot*. O que os separa e que o `@kamba/core-ts` declara o
        `ioredis` em `dependencies` — pelo que ele entra por uma aresta que
        **alguem declara**, e e essa a regra. Uma correccao que cortasse os
        *peers* todos tirava o `ioredis` a quatro servicos.
        """
        for servico in ("services/gwy", "services/com", "services/onboarding-web"):
            with self.subTest(servico=servico):
                nomes = {
                    x.rsplit("@", 1)[0]
                    for x in pnpm_lock.fecho(servico, self.grafo).terceiros
                }
                self.assertIn("ioredis", nomes)
                self.assertIn("bullmq", nomes)

    def test_as_optionaldependencies_verdadeiras_continuam_a_contar(self) -> None:
        """Nao se corta o grupo: corta-se o *peer* opcional dentro dele.

        Os seis `@msgpackr-extract/*` sao `optionalDependencies` a serio do
        `msgpackr-extract`, e estao no fecho dos quatro servicos. Se a regra
        tivesse sido «ignorar `optionalDependencies`», desapareciam.
        """
        nomes = {
            x.rsplit("@", 1)[0]
            for x in pnpm_lock.fecho("services/gwy", self.grafo).terceiros
        }
        binarios = {n for n in nomes if n.startswith("@msgpackr-extract/")}
        self.assertEqual(len(binarios), 6, sorted(binarios))

    def test_o_pg_e_lido_como_par_opcional_do_bullmq(self) -> None:
        """A leitura de `packages:` que a regra usa, medida directamente."""
        pares = self.grafo.pares_opcionais.get("bullmq@6.3.11", frozenset())
        self.assertEqual(pares, frozenset({"bullmq-otel", "ioredis", "pg", "redis"}))

    def test_quem_declara_o_pg_continua_a_leva_lo(self) -> None:
        """Cortar a aresta do *peer* nao pode tirar o `pg` a quem o declara."""
        for alvo in ("services/worker-canal", "packages/core-ts"):
            with self.subTest(alvo=alvo):
                nomes = {
                    x.rsplit("@", 1)[0]
                    for x in pnpm_lock.fecho(alvo, self.grafo).terceiros
                }
                self.assertIn("pg", nomes)


if __name__ == "__main__":
    unittest.main()
