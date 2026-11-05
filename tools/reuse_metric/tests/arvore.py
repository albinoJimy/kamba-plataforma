"""O «repositorio de exemplo» que os *Testes Requeridos* do KAM-039 pedem.

Uma arvore sintetica, minima e com o numero de linhas de codigo **controlado**:
cada ficheiro leva exactamente as linhas que lhe pedimos, para que as
percentagens se possam escolher em vez de se descobrirem. E o que permite medir
os casos limite do bloco («69,9% falha, 70,0% passa») sobre ficheiros a serio e
nao sobre um objecto construido a mao.

A forma e a do repositorio verdadeiro, reduzida ao essencial:

```text
ci/regra-de-dois.yaml
pkg/__init__.py                 nucleo
pkg/nucleo.py                   nucleo
pkg/verticais/__init__.py
pkg/verticais/nova/__init__.py  a vertical medida; o ponto de entrada
pkg/verticais/nova/grafo.py     especifico
pkg/verticais/velha/n.py        MISTO: a nova importa de la dois simbolos
db/migr/0001_base.py            antepassada -> partilhado
db/migr/0002_nova.py            da vertical -> especifico
```
"""

from __future__ import annotations

import subprocess

from pathlib import Path

#: Uma linha de codigo que nao faz nada e conta como uma. O `sloc.py` conta
#: linhas com *token* de codigo, pelo que isto e a unidade de medida.
ENCHIMENTO = "_ = 1"


def linhas(quantas: int) -> str:
    """`quantas` linhas de codigo, e nem uma a mais."""
    return "\n".join([ENCHIMENTO] * quantas) + ("\n" if quantas else "")


def escrever(caminho: Path, texto: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")


def _funcao(nome: str, sloc: int) -> str:
    """Uma funcao com exactamente `sloc` linhas de codigo — o `def` incluido."""
    corpo = "".join([f"    {ENCHIMENTO}\n"] * (sloc - 1))
    return f"def {nome}():\n{corpo}\n\n"


DECLARACAO = """\
version: 1

nucleo:
  padroes:
    - "pkg/*"
  excluidos:
    - "*/verticais/*"
    - "*/test_*.py"
  nomes:
    - nova
    - velha

caminho:
  vertical: nova
  entradas:
    - "pkg/verticais/nova/__init__.py"
  pacotes:
    pkg: "pkg"
  especifico:
    - "*/verticais/nova/*"
  misto:
    - "*/verticais/velha/n.py"
  outra_vertical:
    - "*/verticais/velha/outro.py"
  excluido:
    - "*/test_*.py"
  sobreposicoes:
    - caminho: "pkg/verticais/nova/test_declarado.py"
      razao: "ensaio da vertical nova, declarado como sobreposicao legitima"
  migracoes:
    pasta: "db/migr"
    proprias:
      - "0002_nova.py"
  limiar: 70
"""


def montar(
    raiz: Path,
    *,
    nucleo: int = 60,
    especifico: int = 20,
    simbolo_partilhado: int = 5,
    migracao_base: int = 10,
    migracao_nova: int = 5,
    declaracao: str = DECLARACAO,
) -> Path:
    """Escreve a arvore e devolve a raiz. Os tamanhos sao em linhas de codigo.

    Cada parametro e o numero de linhas de codigo do seu pedaco. A conta do
    reuso **nao** se afirma aqui: afirma-se no teste, que e quem a tem de
    saber. Aqui so se garante que cada pedaco tem o tamanho pedido — e e isso
    que torna os casos limite escolhiveis em vez de descobriveis.
    """
    escrever(raiz / "ci" / "regra-de-dois.yaml", declaracao)

    escrever(raiz / "pkg" / "__init__.py", "")

    # **O nucleo importa a OUTRA vertical**, e nao e enfeite: espelha o
    # acoplamento verdadeiro do `tls/catalogo.py`, que e partilhado e agrega os
    # catalogos das duas verticais. E dele que vem a classe `outra_vertical` —
    # alcancada pelo fecho, e nem partilhada nem da vertical nova. Sem este
    # `import`, o `outro.py` nunca era alcancado e a classe nao se podia medir.
    escrever(
        raiz / "pkg" / "nucleo.py",
        "from .verticais.velha import outro\n" + linhas(nucleo - 1),
    )
    escrever(raiz / "pkg" / "verticais" / "__init__.py", "")
    escrever(raiz / "pkg" / "verticais" / "velha" / "__init__.py", "")
    escrever(
        raiz / "pkg" / "verticais" / "nova" / "__init__.py",
        "from .grafo import construir\n",
    )

    # O ficheiro MISTO: tres simbolos, e a vertical nova importa dois.
    #
    # Construido por concatenacao e nao por `dedent` de um f-string: um corpo
    # ja indentado dentro de um `dedent` da indentacao invalida, e a primeira
    # versao deste apoio escrevia Python que nao compilava — com nove testes a
    # falhar por uma razao que nao tinha nada a ver com o que mediam.
    escrever(
        raiz / "pkg" / "verticais" / "velha" / "n.py",
        _funcao("partilhado_um", simbolo_partilhado)
        + _funcao("partilhado_dois", simbolo_partilhado)
        + _funcao("so_da_velha", 41),
    )
    escrever(raiz / "pkg" / "verticais" / "velha" / "outro.py", linhas(30))

    # As duas primeiras linhas sao os `import`, e contam como codigo: e dai que
    # sai a lista de simbolos do ficheiro misto, e e por isso que o `especifico`
    # pedido desconta duas.
    escrever(
        raiz / "pkg" / "verticais" / "nova" / "grafo.py",
        "from ..velha.n import partilhado_dois, partilhado_um\n"
        "from ...nucleo import _\n" + linhas(especifico - 2),
    )

    escrever(
        raiz / "db" / "migr" / "0001_base.py",
        'revision = "0001"\ndown_revision = None\n' + linhas(migracao_base - 2),
    )
    escrever(
        raiz / "db" / "migr" / "0002_nova.py",
        'revision = "0002"\ndown_revision = "0001"\n' + linhas(migracao_nova - 2),
    )
    _versionar(raiz)
    return raiz


def _versionar(raiz: Path) -> None:
    """Faz da arvore um *worktree* do `git`, porque a medida le de la.

    **Nao e cerimonia de ensaio.** O `fonte.py` enumera os ficheiros com
    `git ls-files` e nao com `rglob`, pela razao que o cabecalho dele da: a
    partir da raiz do *checkout* principal, o `rglob` casava as copias dentro
    dos worktrees irmaos e multiplicava o numerador por dez. Um apoio que
    injectasse a lista de ficheiros em vez de versionar a arvore deixava de
    exercitar esse caminho — e o defeito podia voltar sem nenhum ensaio o ver.

    `-c` em vez de configuracao global: a identidade e deste `commit` e nao da
    maquina, e um apoio que escrevesse no `~/.gitconfig` de quem o corre era
    efeito colateral fora do seu ambito.
    """
    # Os `-c` vao **antes** do subcomando e depois do `-C <raiz>`; escrevê-los
    # entre o `-C` e o caminho faz o `git` ler o caminho como valor do `-c`.
    base = [
        "git",
        "-C",
        str(raiz),
        "-c",
        "user.name=apoio",
        "-c",
        "user.email=apoio@exemplo.invalido",
        "-c",
        "commit.gpgsign=false",
    ]
    # `--template=` vazio salta a copia dos *hooks* de exemplo, que e a parte
    # lenta de um `init` em Windows e nao serve a nada aqui.
    for argumentos in (
        ["init", "--quiet", "--template="],
        ["add", "-A"],
        ["commit", "--quiet", "-m", "apoio"],
    ):
        subprocess.run([*base, *argumentos], check=True, capture_output=True)
