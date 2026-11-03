"""A chave do cache do `.venv` distingue a versao de patch do interpretador.

Isto existe pela razao de sempre neste repositorio: **nao ha *lint* de
*workflows*** (`docs/ci.md` §7, lacuna 15), e a accao
`.github/actions/preparar/action.yaml` e o arranque de **treze** *jobs* — os
sete *gates* do `ci.yaml` mais as seis fatias do `mutacoes.yaml`, que sao um
bloco so e uma matriz de seis. Uma alteracao de uma linha ali apaga o arranque
de todos eles e nada o acusa.

**O escape que o paga, medido a 2026-11-03 na corrida `41636240093`.** A chave
era `venv-<os>-<hash dos requirements>` e nao dizia nada sobre o interpretador,
enquanto o `python-version: "3.12"` flutua no patch de proposito. Um `.venv`
leva o `bin/python3` como symlink para `/opt/hostedtoolcache/Python/<versao>/x64`:
quando a imagem dos runners rolou de `3.12.15` para `3.12.16`, a entrada de 25 de
Outubro passou a ser um symlink pendurado em qualquer runner ja rolado. Nessa
corrida os sete *jobs* do `ci.yaml` apanharam a rolagem a meio — **seis em
3.12.15 passaram e o unico em 3.12.16 falhou**, com
`[Errno 2] ... '.venv/bin/python3'` sobre um cache restaurado a 100%.

E nao se cura sozinho: o `actions/cache` so escreve quando ha *miss*, pelo que
com *hit* restaura o mesmo veneno execucao apos execucao. **Durante a rolagem**,
apagar a entrada tambem nao corrige — enquanto ha dois patches em servico,
nenhuma entrada unica serve os dois lados, so muda quem fica partido.

Verifica-se por **texto** e nao por um leitor de YAML, pela mesma medicao do
`test_ci_titulo_do_pr.py`: o `tools/kamba_yaml.py` e um subconjunto e nao le
estes ficheiros.

## O que a revisao adversarial mudou aqui

A primeira versao deste ficheiro tinha quatro ensaios e **deixava passar a
regressao mais provavel do `action.yaml`**: acrescentar `restore-keys:
venv-<os>-` ao lado da chave nova reintroduz o defeito inteiro — a
correspondencia por prefixo volta a restaurar uma entrada de outro patch — e os
quatro ficavam verdes. O passo do `pnpm`, **imediatamente acima no mesmo
ficheiro**, tem essa linha para copiar. A ausencia de `restore-keys` e
*load-bearing*, e agora tem ensaio proprio.

E o *docstring* afirmava assertar «a linha inteira, com o nome da chave»,
invocando a licao do `test_ci_gate9.py`, enquanto a asercao era um `assertIn` de
subcadeia — pelo que um `hashFiles` degradado passava verde. A afirmacao era
falsa e a licao nao estava aplicada; a asercao passou a ser sobre a linha
inteira, e os ficheiros do `hashFiles` **leem-se do `Makefile`** em vez de
estarem escritos aqui.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ACCAO = ROOT / ".github" / "actions" / "preparar" / "action.yaml"
MAKEFILE = ROOT / "Makefile"

#: Os *jobs* que arrancam por esta accao: ficheiro -> {chave do job: quantos
#: *jobs* ele gera}. **Nao e redundancia**: e o terceiro ponto que torna visivel
#: quem fica sem arranque se alguem mexer na accao, no padrao do KAM-157.
#:
#: A coluna da direita e a parte que a primeira versao deste ficheiro nao tinha,
#: e que a revisao adversarial apanhou: o `fatias` e **um** bloco de YAML e
#: **seis** *jobs*. Contar blocos dava sete consumidores onde ha treze *jobs*, e
#: um denominador errado foi precisamente o que custou duas inversoes de
#: raciocinio no dia em que isto se escreveu.
CONSUMIDORES: dict[str, dict[str, int]] = {
    ".github/workflows/ci.yaml": {
        "gate-1-build": 1,
        "gate-2-tipos": 1,
        "gate-4-unit": 1,
        "gate-6-isolamento": 1,
        "gate-7-contratos": 1,
        "gate-8-migracoes": 1,
        "gate-11-supply-chain": 1,
    },
    ".github/workflows/mutacoes.yaml": {"fatias": 6},
}

TOTAL_DE_JOBS = 13


def _blocos_de_jobs(texto: str) -> dict[str, str]:
    """`{chave do job: corpo}` para um *workflow*, a dois espacos de indentacao."""
    seccao = texto[texto.index("\njobs:"):]
    blocos: dict[str, str] = {}
    actual: str | None = None
    linhas: list[str] = []
    for linha in seccao.splitlines(keepends=True):
        cabeca = re.match(r"^  ([a-z0-9][a-z0-9_-]*):\s*$", linha)
        if cabeca:
            if actual:
                blocos[actual] = "".join(linhas)
            actual, linhas = cabeca.group(1), []
        elif actual:
            linhas.append(linha)
    if actual:
        blocos[actual] = "".join(linhas)
    return blocos


def _jobs_da_matriz(bloco: str) -> int:
    """Quantos *jobs* um bloco gera. Sem `matrix`, um."""
    matriz = re.search(r"(?m)^      matrix:\n((?:        .*\n|\n)*)", bloco)
    if not matriz:
        return 1
    total = 1
    for eixo in re.finditer(r"(?m)^        [a-z0-9_-]+: \[([^\]]*)\]\s*$", matriz.group(1)):
        total *= len([v for v in eixo.group(1).split(",") if v.strip()])
    return total


class _ComAccao(unittest.TestCase):
    def setUp(self) -> None:
        self.texto = ACCAO.read_text(encoding="utf-8")
        self.linhas = self.texto.splitlines()

    def passo_do_cache_do_venv(self) -> str:
        """O bloco do passo `cache do venv`, do `- name:` ao passo seguinte."""
        bloco = re.search(
            r"(?m)^( +)- name: cache do venv\n((?:\1  .*\n|\n)*)", self.texto
        )
        self.assertIsNotNone(bloco, "nao encontrei o passo `cache do venv`")
        return bloco.group(0)

    def linha_da_chave(self) -> str:
        chaves = [l for l in self.linhas if l.strip().startswith("key: venv-")]
        self.assertEqual(
            len(chaves), 1,
            "esperava exactamente uma chave de cache do venv em "
            f"{ACCAO.relative_to(ROOT)}; encontrei {len(chaves)}",
        )
        return chaves[0].strip()


class TestChaveDoCacheDoVenv(_ComAccao):
    """A chave tem de distinguir a versao de patch do interpretador."""

    def test_a_chave_e_exactamente_a_forma_esperada(self) -> None:
        """A **linha inteira**, e nao uma subcadeia dela.

        A primeira versao fazia `assertIn` da expressao da versao, o que deixava
        passar um `hashFiles` degradado — menos um ficheiro, ou nenhum — com a
        expressao da versao intacta. Achado da revisao adversarial, e a licao ja
        estava paga no `test_ci_gate9.py`: procurar «em qualquer sitio» deixa
        trocar o resto de sitio sem acusar.
        """
        chave = self.linha_da_chave()
        forma = re.fullmatch(
            r"key: venv-\$\{\{ runner\.os \}\}"
            r"-py\$\{\{ steps\.([A-Za-z0-9_-]+)\.outputs\.python-version \}\}"
            r"-\$\{\{ hashFiles\(([^)]*)\) \}\}",
            chave,
        )
        self.assertIsNotNone(
            forma,
            "a chave do cache do `.venv` nao esta na forma esperada. Tem de "
            "levar a versao de patch do interpretador — sem ela, uma entrada "
            "construida com um patch e um symlink pendurado em qualquer runner "
            f"que sirva outro. Li: {chave!r}",
        )
        # A **ordem** dos ficheiros do `hashFiles` nao e verificada de
        # proposito: o `hashFiles` ordena os caminhos que resolve, logo trocar
        # dois nao muda o digest e nao e um defeito. O **conjunto** e.
        ficheiros = sorted(f.strip().strip("'\"") for f in forma.group(2).split(","))
        self.assertEqual(
            ficheiros, self.requisitos_do_stamp(),
            "o `hashFiles` da chave deixou de indexar exactamente os "
            "pre-requisitos da regra `$(VENV)/.stamp`. Os dois conjuntos tem de "
            "ser o mesmo: a chave existe para invalidar quando eles mudam, e "
            "uma chave que diz indexar «os requirements» e indexa dois de tres "
            "e uma chave que mente",
        )

    def requisitos_do_stamp(self) -> list[str]:
        """Os pre-requisitos da regra `$(VENV)/.stamp`, lidos do `Makefile`.

        Nao estao escritos neste ficheiro de proposito: a chave existe para
        invalidar quando eles mudam, logo as duas listas **tem** de ser a mesma,
        e escrever a segunda aqui era deixa-las divergir. A chave antiga
        indexava dois de tres, e ninguem o notou.
        """
        regra = re.search(
            r"(?m)^\$\(VENV\)/\.stamp:(.*)$", MAKEFILE.read_text(encoding="utf-8")
        )
        self.assertIsNotNone(regra, "nao encontrei a regra `$(VENV)/.stamp` no Makefile")
        return sorted(regra.group(1).split())

    def test_o_passo_do_python_declara_o_id_que_a_chave_cita(self) -> None:
        """A chave cita um `steps.<id>`; esse `id` tem de existir no passo certo.

        Renomear o `id` nos dois sitios e legitimo e passa. Renomear num so
        deixa a chave a citar um passo que nao existe — e uma expressao que nao
        resolve rende **cadeia vazia**, nao erro: a chave degradava-se em
        silencio para a forma antiga, que e exactamente o defeito que este
        ficheiro fecha.
        """
        chave = self.linha_da_chave()
        citados = re.findall(r"steps\.([A-Za-z0-9_-]+)\.outputs\.python-version", chave)
        self.assertEqual(
            len(citados), 1, f"esperava um `steps.<id>.outputs.python-version`; {chave!r}"
        )
        alvo = citados[0]
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

    def test_o_cache_do_venv_nao_tem_restore_keys(self) -> None:
        """A ausencia de `restore-keys` e o que sustenta tudo o resto.

        **O achado de maior valor da revisao adversarial.** Acrescentar
        `restore-keys: venv-${{ runner.os }}-` ao lado da chave nova reintroduz
        o defeito **inteiro**: a correspondencia por prefixo volta a restaurar
        uma entrada construida noutro patch, e a versao na chave deixa de
        decidir coisa nenhuma. Com os quatro ensaios da primeira versao, essa
        variante passava **4/4 verde**.

        E e a regressao mais provavel deste ficheiro, porque o passo `cache do
        pnpm` — tres linhas acima — tem exactamente essa linha para copiar. La
        e segura (armazem enderecado por conteudo, sem symlinks para a
        toolcache); aqui nao.
        """
        passo = self.passo_do_cache_do_venv()
        self.assertNotRegex(
            passo, r"(?m)^ +restore-keys:",
            "o passo `cache do venv` ganhou `restore-keys`. Isso desfaz a "
            "correccao: a correspondencia por prefixo restaura uma entrada de "
            "outro patch do interpretador, que e o defeito que a versao na "
            "chave existe para fechar. O `restore-keys` do `cache do pnpm` "
            "logo acima e seguro porque o armazem do pnpm e enderecado por "
            "conteudo; este nao e",
        )


class TestSuperficieDaGuarda(_ComAccao):
    """Esta guarda le um ficheiro so; tem de acusar se deixar de bastar."""

    def test_a_accao_e_o_unico_sitio_que_define_um_cache_do_venv(self) -> None:
        """Varre *workflows* **e** outras accoes compostas, `.yaml` e `.yml`.

        A primeira versao varria so `.github/workflows/*.yaml`, e passava verde
        com uma copia em `*.yml` ou noutra accao composta. A segunda nao e
        hipotetica: o proprio `mutacoes.yaml` documenta que «uma segunda receita
        **divergiu** da primeira sem ninguem notar durante onze noites».
        """
        alheios = []
        candidatos = [
            *(ROOT / ".github" / "workflows").glob("*.yaml"),
            *(ROOT / ".github" / "workflows").glob("*.yml"),
            *(ROOT / ".github" / "actions").glob("*/action.yaml"),
            *(ROOT / ".github" / "actions").glob("*/action.yml"),
        ]
        for ficheiro in sorted(set(candidatos)):
            if ficheiro == ACCAO:
                continue
            if re.search(r"(?m)^ +path: \.venv\s*$", ficheiro.read_text(encoding="utf-8")):
                alheios.append(str(ficheiro.relative_to(ROOT)).replace("\\", "/"))
        self.assertEqual(
            alheios, [],
            "ha um cache do `.venv` definido fora da accao `preparar`; os "
            "ensaios deste ficheiro so leem a accao, pelo que a copia ficaria "
            "sem verificacao nenhuma",
        )


class TestConsumidoresDaAccao(unittest.TestCase):
    """Conta os consumidores **e os jobs**, que e a parte que se esquece.

    A hipotese que explicou o escape de 2026-11-03 so se conseguiu testar por se
    saber quantos *jobs* partilham esta entrada: uma previsao sobre
    infraestrutura partilhada e uma previsao sobre **todos** os consumidores
    dela. Se este numero andar sem ninguem reparar, o proximo raciocinio da
    mesma familia parte de um denominador errado — que foi o que aconteceu duas
    vezes no dia em que isto se escreveu, uma em cada sentido.
    """

    def test_os_consumidores_sao_os_declarados(self) -> None:
        vistos: dict[str, dict[str, int]] = {}
        for ficheiro in sorted(
            set(
                [*(ROOT / ".github" / "workflows").glob("*.yaml"),
                 *(ROOT / ".github" / "workflows").glob("*.yml")]
            )
        ):
            texto = ficheiro.read_text(encoding="utf-8")
            if "\njobs:" not in texto:
                continue
            nome = str(ficheiro.relative_to(ROOT)).replace("\\", "/")
            for chave, bloco in _blocos_de_jobs(texto).items():
                # Linhas comentadas nao contam: um `uses:` dentro de um
                # comentario nao arranca nada.
                vivas = "\n".join(
                    l for l in bloco.splitlines() if not l.lstrip().startswith("#")
                )
                if "uses: ./.github/actions/preparar" in vivas:
                    vistos.setdefault(nome, {})[chave] = _jobs_da_matriz(bloco)
        self.assertEqual(
            vistos, CONSUMIDORES,
            "a lista de consumidores da accao `preparar` mudou. Se foi "
            "deliberado, corrija o `CONSUMIDORES` e o `TOTAL_DE_JOBS` deste "
            "ficheiro — e corrija tambem qualquer texto que cite o numero",
        )

    def test_o_total_de_jobs_e_o_declarado(self) -> None:
        """Um bloco pode ser seis *jobs*: e o caso do `fatias`."""
        self.assertEqual(
            sum(n for job in CONSUMIDORES.values() for n in job.values()),
            TOTAL_DE_JOBS,
            "o `TOTAL_DE_JOBS` deixou de bater com o `CONSUMIDORES`",
        )


if __name__ == "__main__":
    unittest.main()
