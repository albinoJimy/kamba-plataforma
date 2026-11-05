"""A base do ramo actual — KAM-180.

Responde a **uma** pergunta: «este ramo nasceu numa linha que a `publico/main`
contem?». E responde-a pela **origem** do ramo e nao pelo seu estado actual, que
e a distincao que da substancia ao ticket.

**Porque e que a pergunta nao e obvia.** Este repositorio tem dois remotos **sem
antepassado comum**: o `publico` (`albinoJimy/kamba-plataforma`) e o activo, e o
`origin` (`albinoJimy/kamba`) e a linha antiga. A ferramenta que abre *worktrees*
ramifica de `origin/<default-branch>`, pelo que um *worktree* novo nasce em
`f344990` — o *merge* do PR `#47` da linha antiga — e nao na `publico/main`.
Medido a 2026-11-04: **tres sessoes em tres**, e 33 dos 45 ramos `claude/*`
parados nesse *commit*. O defeito e sistematico, nao intermitente.

**A causa esta fora deste repositorio.** Quem abre o *worktree* e a aplicacao que
corre as sessoes, nao e codigo da KAMBA, e nada neste *backlog* o pode corrigir.
O que este modulo entrega e **deteccao e reparacao**: diz onde o ramo nasceu,
nomeia o comando exacto que o repara, e sai. Nao escreve, nao ramifica, nao
funde — a reparacao e de quem corre, que e quem sabe se tem trabalho por
*commitar*.

Tres formas de medir isto falham **em silencio**, e cada uma ja custou tempo. As
tres estao recusadas por ensaio em `tests/test_base.py`, nao por comentario:

1. **O `merge-base` sai 1 e nao imprime nada.** Entre as duas linhas,
   `git merge-base <ramo> refs/remotes/publico/main` sai com codigo 1 e **sem
   saida**. Um *script* que capture a saida e nao leia o codigo fica com a
   variavel vazia — e a armadilha e a variavel **sem aspas**: `git diff $BASE
   $ramo` colapsa em `git diff $ramo`, que devolve uma resposta plausivel e se le
   como «este ramo nao tem nada a mais do que a base». Com aspas falha alto
   (`fatal: ambiguous argument ''`) e nao engana ninguem. Foi assim que se
   estiveram a apagar sete *worktrees* cujo trabalho a `publico/main` nao contem.
   Daqui vem a forma de `e_antepassado`: usa `--is-ancestor`, que **nao imprime
   nada em nenhuma das respostas**, pelo que o codigo de saida nao e uma das
   fontes — e a unica.
2. **O `rev-list` responde, e a resposta nao quer dizer o que parece.**
   `git rev-list --left-right --count f344990...HEAD` **responde** entre linhas
   sem antepassado comum — `231\t164`, medido a 2026-11-05 — porque `...` em
   `rev-list` e diferenca simetrica e nao precisa de antepassado comum. Le-se como
   «tenho 164 a frente e 231 atras» quando o que se passa e que **nao ha relacao
   nenhuma**: o 231 e a linha antiga inteira e fica fixo. Quem diz a verdade e o
   `git diff A...HEAD`, com `fatal: no merge base`. Este modulo nao usa `rev-list`
   para decidir, e ha ensaio que o fixa.
3. **A pasta `.claude/skills/` responde a pergunta errada.** Na linha errada
   chama-se `agentic-engineering` e na certa `software-factory` — medido por
   `git ls-tree`, **7** ficheiros contra **12**. Mas **muda sozinha quando se
   ramifica**, pelo que responde «onde estou **agora**» e nao «**fui** cortado»:
   um ramo reparado passaria a ser indistinguivel de um que nunca foi cortado.
   Esta armadilha apanhou duas leituras no mesmo dia. **Este modulo nao le essa
   pasta** — nem para confirmar — e isso e um controlo com ensaio proprio e
   mutacao propria, nao uma intencao escrita aqui.

**O que ele le, e porque e que e o ficheiro cru.** A origem sai da **coluna do
valor antigo** da primeira entrada do *reflog*, lida de
`logs/refs/heads/<ramo>` dentro do `--git-common-dir`. **Nao e o `git reflog
show` nu**, que imprime o valor **novo**: num ramo ja reparado da
`branch: Reset to refs/remotes/publico/main` com o *commit* de **depois** da
reparacao, e a resposta seria «conforme» — o falso negativo exacto que este
ticket existe para fechar. Medido a 2026-11-05 no
`claude/manual-provider-auditado-e03ef3`: o `reflog show` da
`c3b1fe2 ... Reset to ...` e o ficheiro cru da `f3449906... c3b1fe2...` na
primeira linha. E nao ha marcador de formato para a coluna antiga — o `git log
-g` expoe `%gd`, `%gn`, `%ge` e `%gs`, e nenhum deles e o valor anterior —, pelo
que o ficheiro cru nao e preferencia, e o unico sitio onde o valor esta.

**E a mensagem nunca e lida.** `ler_entrada` descarta tudo o que vem depois da
tabulacao. Decidir pela mensagem repete o defeito do `reflog show` por outra
via: `branch: Reset to refs/remotes/publico/main` nomeia a referencia **certa**
numa entrada cujo valor antigo e `f344990`.

**O valor nulo, e porque e que a regra nao e so «a coluna antiga».** Numa entrada
de criacao (`branch: Created from X`) a coluna antiga e o OID nulo, porque antes
dela o ramo nao existia; o valor que interessa esta na coluna **nova**. Numa
entrada de reparacao (`branch: Reset to X`) a coluna antiga e o *commit* de onde
o ramo vinha, que e precisamente a origem. Logo a regra e: a coluna antiga,
**excepto quando e o OID nulo**, e ai a nova. O nulo e inequivoco, pelo que a
excepcao nao e uma heuristica. A prosa do ticket diz «a coluna do valor antigo»;
isto e mais preciso do que ela e nao diferente dela — o caso de criacao e o unico
em que a coluna antiga nao nomeia *commit* nenhum.

**Falha fechada.** Sem *reflog* — e ha exemplares reais: o ramo que a aplicacao
gerou para esta sessao nao tem ficheiro de *log* nenhum — o veredicto e
`DESCONHECIDO` e o codigo de saida e 2. «Nao sei» nunca se imprime como
«conforme».

**Onde isto para, e e deliberado.** Fazer deste modulo um portao que trava fusoes
e **regra de bloqueio, logo decisao do fundador**. O que o ticket entrega e o
instrumento e a medicao, nao a ligacao a um *gate*: nenhum *job* novo no
`ci.yaml` e nenhum contexto novo no *ruleset* da `main`. E a mesma fronteira que
o KAM-174 escreveu.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

#: O OID nulo, que e o que o git escreve na coluna antiga de uma entrada de
#: criacao. Quarenta zeros: o git escreve-o com o comprimento do algoritmo em
#: uso, e este repositorio e SHA-1.
NULO = "0" * 40

#: A referencia que conta. **Com o `refs/remotes/` por extenso**, e nao
#: `publico/main`: um ramo local chamado `publico/main` resolveria primeiro, e a
#: pergunta passava a ser sobre outra coisa sem ninguem notar.
REFERENCIA_PADRAO = "refs/remotes/publico/main"

CONFORME = "conforme"
RECUSADO = "recusado"
DESCONHECIDO = "desconhecido"

#: Codigo de saida por estado. Segue a convencao do `lint_arch`: 0 conforme,
#: 1 achado, 2 erro — e `DESCONHECIDO` e 2 e nao 1 porque nao e um achado sobre o
#: ramo, e uma impossibilidade de medir. As duas sao nao-zero, que e o que
#: «falha fechada» exige; a distincao serve para quem automatiza.
CODIGOS = {CONFORME: 0, RECUSADO: 1, DESCONHECIDO: 2}


@dataclasses.dataclass(frozen=True)
class Entrada:
    """Uma linha do *reflog* cru, ja partida nas suas colunas.

    A mensagem **nao** entra: e lixo para esta pergunta, e guarda-la convidava a
    decidir por ela. Ver o cabecalho do modulo.
    """

    velho: str
    novo: str


@dataclasses.dataclass(frozen=True)
class Veredicto:
    estado: str
    ramo: str | None
    origem: str | None
    razao: str
    referencia: str = REFERENCIA_PADRAO

    @property
    def codigo(self) -> int:
        return CODIGOS[self.estado]


def _git(raiz: Path, *argumentos: str) -> subprocess.CompletedProcess[str]:
    """Corre o git sem `check`: aqui o codigo de saida e um resultado, nao um erro.

    `check=True` levantaria excepcao no caso que mais interessa — o `merge-base`
    a sair 1 —, e quem apanhasse a excepcao ficava sem distinguir «nao e
    antepassado» de «a referencia nao existe».
    """
    return subprocess.run(
        ["git", *argumentos],
        cwd=raiz,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def ramo_actual(raiz: Path) -> str | None:
    """O ramo actual, ou `None` se nao houver um (`HEAD` solto, por exemplo)."""
    resultado = _git(raiz, "rev-parse", "--abbrev-ref", "HEAD")
    if resultado.returncode != 0:
        return None
    nome = resultado.stdout.strip()
    # Num `HEAD` solto o git responde literalmente `HEAD`, que nao e um ramo.
    # Devolve-lo levava o passo seguinte a procurar `logs/refs/heads/HEAD`.
    if not nome or nome == "HEAD":
        return None
    return nome


def caminho_do_reflog(raiz: Path, ramo: str) -> Path | None:
    """O ficheiro de *log* do ramo, dentro do `--git-common-dir`.

    **O comum e nao o do *worktree***: num *worktree* o `--git-dir` e
    `.git/worktrees/<nome>`, e os *logs* dos ramos vivem no directorio comum.
    Procurar no do *worktree* nao encontrava ficheiro nenhum e todo o
    repositorio respondia `DESCONHECIDO` — um falso «nao sei» tao mau como um
    falso «conforme», porque o instrumento ficava calado onde devia morder.
    """
    resultado = _git(raiz, "rev-parse", "--git-common-dir")
    if resultado.returncode != 0:
        return None
    bruto = resultado.stdout.strip()
    if not bruto:
        return None
    # O git responde um caminho relativo (`.git`) quando se corre na raiz, e
    # absoluto a partir de um subdirectorio.
    comum = Path(bruto)
    if not comum.is_absolute():
        comum = raiz / comum
    return comum / "logs" / "refs" / "heads" / ramo


def _hexadecimal(valor: str) -> bool:
    return len(valor) in (40, 64) and all(
        caracter in "0123456789abcdef" for caracter in valor
    )


def ler_entrada(linha: str) -> Entrada | None:
    """Parte a primeira linha do *reflog* cru nas duas colunas que decidem.

    A forma e `<velho> <novo> <identidade> <tempo> <fuso>\\tmensagem`. **Tudo o
    que vem depois da tabulacao e descartado aqui**, e nao mais adiante: a
    mensagem de uma reparacao nomeia a referencia certa numa entrada cujo valor
    antigo e o *commit* errado, pelo que guarda-la era guardar uma armadilha.

    Devolve `None` para uma linha que nao tenha as duas colunas na forma de um
    OID — fail-closed: um *log* ilegivel nao pode parecer um ramo conforme.
    """
    campos = linha.split()
    if len(campos) < 2:
        return None
    velho, novo = campos[0], campos[1]
    if not _hexadecimal(velho) or not _hexadecimal(novo):
        return None
    return Entrada(velho=velho, novo=novo)


def origem_do_ramo(raiz: Path, ramo: str) -> tuple[str | None, str]:
    """O *commit* onde o ramo nasceu, e a razao quando nao se sabe.

    Le a **primeira** entrada do *reflog* cru — a mais antiga, que e a que fala
    da origem. A ultima fala do presente, que e a pergunta que este modulo
    recusa.
    """
    caminho = caminho_do_reflog(raiz, ramo)
    if caminho is None:
        return None, "nao foi possivel localizar o directorio de git comum"
    if not caminho.is_file():
        return None, (
            f"o ramo {ramo!r} nao tem reflog ({caminho}): a origem nao se pode ler"
        )
    try:
        with caminho.open("r", encoding="utf-8", errors="replace") as ficheiro:
            primeira = ficheiro.readline()
    except OSError as excepcao:
        return None, f"nao foi possivel ler {caminho}: {excepcao}"
    if not primeira.strip():
        return None, f"o reflog de {ramo!r} esta vazio ({caminho})"
    entrada = ler_entrada(primeira)
    if entrada is None:
        return None, f"a primeira entrada do reflog de {ramo!r} nao e legivel"
    # A coluna antiga, **excepto** quando e o OID nulo. Ver o cabecalho: numa
    # entrada de criacao o ramo nao existia antes dela, pelo que o valor que
    # nomeia a origem esta na coluna nova.
    if entrada.velho != NULO:
        return entrada.velho, "coluna do valor antigo da primeira entrada do reflog"
    return entrada.novo, "coluna do valor novo da entrada de criacao do ramo"


def e_antepassado(raiz: Path, commit: str, referencia: str) -> bool | None:
    """`True` se `commit` estiver na linha que `referencia` contem.

    **Decidido pelo codigo de saida, que e o unico sinal que existe**:
    `git merge-base --is-ancestor` nao imprime nada em nenhuma das respostas, pelo
    que um *script* que capture a saida fica com a string vazia nas tres e nao
    distingue nada. 0 = sim, 1 = nao, qualquer outro = nao se sabe — tipicamente
    128, quando a referencia nao existe localmente porque ninguem fez o `fetch`
    com *refspec*.
    """
    resultado = _git(raiz, "merge-base", "--is-ancestor", commit, referencia)
    if resultado.returncode == 0:
        return True
    if resultado.returncode == 1:
        return False
    return None


def avaliar(
    raiz: Path,
    ramo: str | None = None,
    referencia: str = REFERENCIA_PADRAO,
) -> Veredicto:
    """O veredicto sobre a base do ramo.

    Tres leituras, por esta ordem, e cada uma com o seu codigo de saida
    verificado: o ramo actual, a origem pelo *reflog* cru, e o parentesco pelo
    `merge-base --is-ancestor`.
    """
    ramo = ramo or ramo_actual(raiz)
    if ramo is None:
        return Veredicto(
            estado=DESCONHECIDO,
            ramo=None,
            origem=None,
            razao=(
                "nao foi possivel determinar o ramo actual (HEAD solto?): "
                "passe o nome do ramo explicitamente"
            ),
            referencia=referencia,
        )

    origem, porque = origem_do_ramo(raiz, ramo)
    if origem is None:
        return Veredicto(
            estado=DESCONHECIDO, ramo=ramo, origem=None, razao=porque,
            referencia=referencia,
        )

    resposta = e_antepassado(raiz, origem, referencia)
    if resposta is None:
        return Veredicto(
            estado=DESCONHECIDO,
            ramo=ramo,
            origem=origem,
            razao=(
                f"o git nao conseguiu comparar {origem[:7]} com {referencia}: "
                f"a referencia existe localmente? "
                f"(`git fetch publico main:{referencia} --force`)"
            ),
            referencia=referencia,
        )
    if resposta:
        return Veredicto(
            estado=CONFORME, ramo=ramo, origem=origem,
            razao=f"a origem esta na linha de {referencia} ({porque})",
            referencia=referencia,
        )
    return Veredicto(
        estado=RECUSADO,
        ramo=ramo,
        origem=origem,
        razao=(
            f"a origem {origem[:7]} NAO esta na linha de {referencia} ({porque})"
        ),
        referencia=referencia,
    )


def texto_da_reparacao(veredicto: Veredicto) -> str:
    """O comando exacto que repara, no corpo do veredicto e nao num documento.

    **Nao e `git reset --hard`**: esta bloqueado por guarda nesta maquina, e com a
    arvore limpa o `git checkout -b` faz o mesmo e ainda deixa o ramo com um nome
    que o `lint_arch branch` aceita — o `claude/...` gerado pela aplicacao nao
    passa nesse *lint*, e o `pre-push` recusa-o.

    **E o `fetch` leva *refspec***: um `git fetch publico main` sem ela so mexe no
    `FETCH_HEAD` e deixa a referencia remota parada onde estava, pelo que o
    `checkout` seguinte ramificaria do mesmo *commit* velho e a reparacao parecia
    nao ter efeito.
    """
    return (
        "\n"
        "  Como reparar (a arvore tem de estar limpa; committa ou guarda antes):\n"
        "\n"
        f"      git fetch publico main:{veredicto.referencia} --force\n"
        f"      git checkout -b fix/KAM-NNN-<slug> {veredicto.referencia}\n"
        "\n"
        "  O `fetch` leva refspec de proposito: sem ela so o FETCH_HEAD se move, e\n"
        "  a referencia remota fica parada onde estava.\n"
        "  O nome tem de ser `feature/KAM-NNN-<slug>` ou `fix/KAM-NNN-<slug>`: o\n"
        "  `claude/...` que a aplicacao gera nao passa no `lint_arch branch` e o\n"
        "  `pre-push` recusa-o.\n"
        "  **Nao** uses `git reset --hard`: esta bloqueado por guarda nesta maquina,\n"
        "  e com a arvore limpa o `checkout -b` faz o mesmo.\n"
        "\n"
        "  Confirma depois, dentro do worktree, que os dois dao o mesmo:\n"
        "\n"
        "      git rev-parse --short HEAD\n"
        f"      git rev-parse --short {veredicto.referencia}\n"
        "\n"
        "  O ramo velho fica onde estava, e isso e util: a ponta abandonada e a\n"
        "  impressao digital que permite responder \"fui cortado?\" depois da\n"
        "  reparacao. Nao o apagues antes de o PR fundir.\n"
    )
