"""A chave do cache do `.venv` leva a versao de patch do interpretador.

Isto existe pela razao de sempre neste repositorio: **nao ha *lint* de
*workflows*** (`docs/ci.md` §7, lacuna 15), e a accao
`.github/actions/preparar/action.yaml` e o arranque de **sete** *jobs* — os
*gates* 1, 2, 4, 6, 7, 8 e 11 — mais as seis fatias da prova nocturna. Uma
alteracao de uma linha ali apaga o arranque de todos eles e nada o acusa.

**O escape que o paga, medido a 2026-11-03 na corrida `41636240093`.** A chave
era `venv-<os>-<hash dos requirements>` e nao dizia nada sobre o interpretador,
enquanto o `python-version: "3.12"` flutua no patch de proposito. Um `.venv`
leva o `bin/python3` como symlink para `/opt/hostedtoolcache/Python/<versao>/x64`:
quando a imagem dos runners rolou de `3.12.15` para `3.12.16`, a entrada de 25 de
Outubro passou a ser um symlink pendurado em qualquer runner ja rolado. Nessa
corrida os sete *jobs* apanharam a rolagem a meio — **seis em 3.12.15 passaram e
o unico em 3.12.16 falhou**, com `[Errno 2] ... '.venv/bin/python3'` sobre um
cache restaurado a 100%.

E nao se cura sozinho: o `actions/cache` so escreve quando ha *miss*, pelo que
com *hit* restaura o mesmo veneno execucao apos execucao. Apagar a entrada
tambem nao corrige — durante a rolagem **nenhuma** entrada unica serve os dois
lados, so muda quem fica partido. A correccao tem de ser na chave.

Verifica-se por **texto** e nao por um leitor de YAML, pela mesma medicao do
`test_ci_titulo_do_pr.py`: o `tools/kamba_yaml.py` e um subconjunto e nao le
estes ficheiros.

E asserta-se a **linha inteira**, com o nome da chave. A licao esta paga no
`test_ci_gate9.py`: a primeira versao procurava as expressoes «em qualquer sitio
do bloco», a revisao adversarial trocou duas variaveis de sitio, e as asercoes
continuaram verdes.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ACCAO = ROOT / ".github" / "actions" / "preparar" / "action.yaml"

#: Os *jobs* que arrancam por esta accao, escritos aqui tambem. **Nao e
#: redundancia**: e o terceiro ponto que torna visivel quem fica sem arranque se
#: alguem mexer na accao, no padrao do KAM-157.
CONSUMIDORES = ("gate 1", "gate 2", "gate 4", "gate 6", "gate 7", "gate 8", "gate 11")


class TestChaveDoCacheDoVenv(unittest.TestCase):
    """A chave tem de distinguir a versao de patch do interpretador."""

    def setUp(self) -> None:
        self.texto = ACCAO.read_text(encoding="utf-8")
        self.linhas = self.texto.splitlines()

    def _linha_da_chave(self) -> str:
        chaves = [l for l in self.linhas if l.strip().startswith("key: venv-")]
        self.assertEqual(
            len(chaves), 1,
            "esperava exactamente uma chave de cache do venv em "
            f"{ACCAO.relative_to(ROOT)}; encontrei {len(chaves)}",
        )
        return chaves[0].strip()

    def test_a_chave_do_venv_leva_a_versao_do_interpretador(self) -> None:
        """Sem isto, a entrada envenena-se na rolagem da imagem dos runners."""
        chave = self._linha_da_chave()
        self.assertIn(
            "${{ steps.python.outputs.python-version }}", chave,
            "a chave do cache do `.venv` nao distingue a versao de patch do "
            "interpretador. Uma entrada construida com um patch e um symlink "
            "pendurado em qualquer runner que sirva outro, e o `actions/cache` "
            "nunca a reescreve enquanto houver *hit*. Medido a 2026-11-03: "
            f"chave actual -> {chave!r}",
        )

    def test_o_passo_do_python_declara_o_id_que_a_chave_cita(self) -> None:
        """A chave cita um `steps.<id>`; esse `id` tem de existir no passo certo.

        Renomear o `id` nos dois sitios e legitimo e passa. Renomear num so
        deixa a chave a citar um passo que nao existe — e uma expressao que nao
        resolve rende **cadeia vazia**, nao erro: a chave degradava-se em
        silencio para a forma antiga, que e exactamente o defeito que este
        ficheiro fecha.
        """
        chave = self._linha_da_chave()
        citados = re.findall(r"steps\.([A-Za-z0-9_-]+)\.outputs\.python-version", chave)
        self.assertEqual(
            len(citados), 1, f"esperava um `steps.<id>.outputs.python-version`; {chave!r}"
        )
        alvo = citados[0]

        # O `id` tem de ser o do passo que corre o `setup-python`, e nao o de um
        # passo qualquer: procura-se dentro do bloco desse passo.
        bloco = re.search(
            r"(?m)^( +)- name: .*\n(?:\1  .*\n|\n)*?\1  uses: actions/setup-python@[^\n]*\n"
            r"(?:\1  .*\n|\n)*",
            self.texto,
        )
        self.assertIsNotNone(bloco, "nao encontrei o passo do `actions/setup-python`")
        self.assertRegex(
            bloco.group(0), rf"(?m)^ +id: {re.escape(alvo)}$",
            f"a chave cita `steps.{alvo}`, mas o passo do `setup-python` nao "
            f"declara `id: {alvo}`. Uma expressao que nao resolve rende cadeia "
            "vazia, e a chave volta em silencio a nao distinguir o patch",
        )

    def test_a_accao_continua_a_ser_o_unico_sitio_que_define_este_cache(self) -> None:
        """Se alguem copiar o passo para um workflow, esta guarda deixa de bastar."""
        outros = []
        for ficheiro in sorted((ROOT / ".github" / "workflows").glob("*.yaml")):
            if "path: .venv" in ficheiro.read_text(encoding="utf-8"):
                outros.append(str(ficheiro.relative_to(ROOT)))
        self.assertEqual(
            outros, [],
            "ha um cache do `.venv` definido fora da accao `preparar`; esta "
            "guarda so le a accao, pelo que a copia ficaria sem verificacao",
        )

    def test_os_consumidores_da_accao_estao_todos_no_ci(self) -> None:
        """Conta os consumidores, que e a parte que se esquece.

        A hipotese que explicou o escape de 2026-11-03 so se conseguiu testar
        por se saber **quantos** *jobs* partilham esta entrada: uma previsao
        sobre infraestrutura partilhada e uma previsao sobre todos os seus
        consumidores. Se este numero andar sem ninguem reparar, o proximo
        raciocinio da mesma familia parte de um denominador errado.
        """
        ci = (ROOT / ".github" / "workflows" / "ci.yaml").read_text(encoding="utf-8")
        blocos = re.split(r"(?m)^  (?=[a-z0-9][a-z0-9_-]*:$)", ci)
        com_accao = [
            b for b in blocos if "uses: ./.github/actions/preparar" in b
        ]
        nomes = []
        for bloco in com_accao:
            nome = re.search(r'(?m)^    name: "?([^"\n]+)"?$', bloco)
            if nome:
                nomes.append(nome.group(1))
        for esperado in CONSUMIDORES:
            with self.subTest(gate=esperado):
                self.assertTrue(
                    any(n.startswith(esperado + " ") for n in nomes),
                    f"o {esperado} deixou de usar a accao `preparar`; se foi "
                    f"deliberado, corrija a lista deste ficheiro. Vi: {nomes}",
                )
        self.assertEqual(
            len(com_accao), len(CONSUMIDORES),
            f"a accao `preparar` passou a ter {len(com_accao)} consumidores no "
            f"`ci.yaml` e a lista deste ficheiro tem {len(CONSUMIDORES)}: {nomes}",
        )


if __name__ == "__main__":
    unittest.main()
