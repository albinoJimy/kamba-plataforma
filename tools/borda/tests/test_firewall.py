"""As regras `nftables` do `host-base` (KAM-077, criterio 4; classe 3 da portabilidade).

Duas perguntas, como no `env_lint`: as regras **desta** arvore estao conformes
(`TestArvoreReal`), e a verificacao morde quando alguem as estraga
(`TestMorde`). Um verde na primeira sem a segunda podia ser um verificador que
nao olha para nada.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from borda import firewall

RAIZ = Path(__file__).resolve().parents[3]
WG = 51820


class TestArvoreReal(unittest.TestCase):
    def setUp(self) -> None:
        self.regras = firewall.do_modelo(RAIZ, WG)

    def test_as_regras_do_host_base_estao_conformes(self) -> None:
        self.assertEqual([str(a) for a in firewall.verificar(self.regras, WG)], [])

    def test_leu_regras_e_nao_um_bloco_vazio(self) -> None:
        # O numero importa: um verde sobre zero regras nao diz nada.
        self.assertIn("table inet kamba_host {", self.regras)
        self.assertIn('iifname "wg0" tcp dport 22 accept', self.regras)
        self.assertNotIn("${", self.regras, "a porta do WireGuard ficou por interpolar")

    def test_a_porta_e_a_do_modulo(self) -> None:
        # A porta das regras e a mesma variavel que o `wg0.conf` usa: mudar uma
        # muda a outra. Com outra porta, a verificacao continua conforme.
        self.assertEqual(firewall.verificar(firewall.do_modelo(RAIZ, 41194), 41194), [])

    def test_o_servico_nao_e_o_da_distribuicao(self) -> None:
        texto = (RAIZ / firewall.MODELO).read_text(encoding="utf-8")
        self.assertIn("ExecStop=/usr/sbin/nft delete table inet kamba_host", texto)
        self.assertNotIn("enable, --now, nftables", texto)
        # E o primeiro passo do `runcmd`, e falha fechado: com `set -e` e a
        # confirmacao de que a tabela ficou carregada, ou o arranque para.
        runcmd = texto.split("\nruncmd:\n", 1)[1]
        passos = runcmd.split("\n  - ")
        primeiro = next(p for p in passos if not p.lstrip().startswith("#"))
        self.assertIn("set -euo pipefail", primeiro)
        self.assertIn("systemctl enable --now kamba-firewall.service", primeiro)
        self.assertIn("if ! nft list table inet kamba_host", primeiro)
        self.assertIn("exit 1", primeiro)


class TestMorde(unittest.TestCase):
    """Cada propriedade do modulo, partida uma a uma sobre as regras reais."""

    def setUp(self) -> None:
        self.regras = firewall.do_modelo(RAIZ, WG)

    def _achados(self, regras: str) -> set[str]:
        return {a.regra for a in firewall.verificar(regras, WG)}

    def _trocar(self, velho: str, novo: str) -> str:
        self.assertIn(velho, self.regras)
        return self.regras.replace(velho, novo)

    def test_ssh_aberto_ao_mundo(self) -> None:
        self.assertIn("ssh-fora-do-tunel", self._achados(self._trocar('iifname "wg0" tcp dport 22 accept', "tcp dport 22 accept")))

    def test_ssh_dentro_de_um_conjunto(self) -> None:
        self.assertIn("ssh-fora-do-tunel", self._achados(self._trocar('iifname "wg0" tcp dport 22 accept', "tcp dport { 22, 2222 } accept")))

    def test_porta_nova_ao_mundo(self) -> None:
        self.assertIn("regra-nao-reconhecida", self._achados(self._trocar("udp dport 51820 accept", "udp dport 51820 accept\n    tcp dport 3000 accept")))

    def test_aberturas_que_a_primeira_versao_deixava_passar(self) -> None:
        # Sete dos oito casos da revisao adversarial (o oitavo, `add rule` fora do
        # bloco, tem ensaio proprio): nenhum tem `dport` sem `iifname`,
        # e todos abrem o host. A lista fechada apanha-os todos.
        casos = {
            "accept-sozinho": "accept",
            "ct-new": "ct state new accept",
            "toda-a-internet": "ip saddr 0.0.0.0/0 accept",
            "todo-o-tcp": "meta l4proto tcp accept",
            "outra-interface": 'iifname "eth0" tcp dport 3306 accept',
            "jump": "jump abre",
            "duas-numa-linha": "udp dport 51820 accept; tcp dport 3306 accept",
        }
        for nome, regra in casos.items():
            with self.subTest(caso=nome):
                regras = self._trocar("udp dport 51820 accept", "udp dport 51820 accept\n    " + regra)
                self.assertIn("regra-nao-reconhecida", self._achados(regras))

    def test_add_rule_fora_do_bloco(self) -> None:
        regras = self.regras + "add rule inet kamba_host input tcp dport 3306 accept\n"
        self.assertIn("fora-da-tabela", self._achados(regras))

    def test_cadeia_auxiliar_que_aceita(self) -> None:
        regras = self._trocar("  chain input {", "  chain abre {\n    accept\n  }\n  chain input {")
        self.assertIn("regra-nao-reconhecida", self._achados(regras))

    def test_flush_ruleset(self) -> None:
        self.assertIn("flush-ruleset", self._achados("flush ruleset\n" + self.regras))

    def test_policy_accept(self) -> None:
        self.assertIn("input-sem-drop", self._achados(self._trocar("policy drop;", "policy accept;")))

    def test_cadeia_no_forward(self) -> None:
        regras = self._trocar(
            "  chain input {",
            "  chain encaminhar {\n    type filter hook forward priority filter; policy drop;\n  }\n  chain input {",
        )
        self.assertIn("forward", self._achados(regras))

    def test_sem_wireguard(self) -> None:
        self.assertIn("sem-wireguard", self._achados(self._trocar("udp dport 51820 accept", "")))

    def test_sem_tabela(self) -> None:
        self.assertIn("sem-tabela", self._achados("table ip outra {\n}\n"))

    def test_comentario_nao_conta(self) -> None:
        self.assertEqual(self._achados(self.regras + "# tcp dport 22 accept\n"), set())


class TestExtrair(unittest.TestCase):
    def test_sem_o_ficheiro(self) -> None:
        with self.assertRaises(firewall.RegrasAusentes):
            firewall.extrair("write_files:\n  - path: /etc/outro\n    content: |\n      x\n")

    def test_sem_content(self) -> None:
        texto = f"write_files:\n  - path: {firewall.CAMINHO_NO_HOST}\n    owner: root\n  - path: /etc/outro\n"
        with self.assertRaises(firewall.RegrasAusentes):
            firewall.extrair(texto)
        with self.assertRaises(firewall.RegrasAusentes):
            firewall.extrair(f"write_files:\n  - path: {firewall.CAMINHO_NO_HOST}\n    owner: root\n")

    def test_para_no_fim_do_bloco(self) -> None:
        texto = (
            f"write_files:\n  - path: {firewall.CAMINHO_NO_HOST}\n    content: |\n"
            "      linha 1\n\n        linha 2\n  - path: /etc/outro\n"
        )
        self.assertEqual(firewall.extrair(texto), "linha 1\n\n  linha 2\n")


if __name__ == "__main__":
    unittest.main()
