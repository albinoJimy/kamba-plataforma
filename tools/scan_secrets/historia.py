"""Gate 9, segunda passagem: os *blobs* que o intervalo do PR acrescenta a historia.

A passagem da arvore (`tree`) ve o que o `git` segue **agora**. Um segredo posto
no commit A e retirado no commit B nao esta na arvore final e passava o gate — e
entrava no `main` com o merge, porque o `main` recebe os dois commits. Esta
passagem le os objectos do intervalo, e nenhuma das duas substitui a outra.

O conjunto a varrer e o do intervalo e nao o do `main` inteiro, e sai de duas
travessias:

* `git rev-list --objects <base>..<head>` — todo o objecto **alcancavel** da
  cabeca e nao da base. Da o conjunto, mas **um** caminho por objecto: o `git`
  imprime cada objecto uma vez, com o nome em que a travessia o encontrou.
* `git log --raw -c` sobre o mesmo intervalo — da **todos** os caminhos e o
  commit em que cada blob entrou, que e o que o criterio de aceitacao exige no
  relatorio e de que a aplicacao das areas permitidas depende.

**O `-c` nao e um detalhe.** Sem ele, `git log --raw` nao imprime sequer o
cabecalho de um merge, e um blob que um merge introduza por si (um *evil merge*)
ficava sem atribuicao — com o unico caminho que o `rev-list` nomeasse. A revisao
adversarial deste ticket construiu a evasao: o mesmo blob acrescentado por um
merge na pasta do canario **e** fora dela, e apagado no commit seguinte. O
`rev-list` nomeava so o caminho do canario, a area permitia-o, e o gate ficava
verde — pela ordem alfabetica da travessia, nao pela politica. Com `-c`, o merge
leva um registo combinado por caminho que difira de **todos** os pais, que e
exactamente o que ele introduz por si: nada num merge limpo, os dois caminhos
naquele ataque. Ver [`../../docs/analises/ANALISE-14-KAM-131-gate-9-na-historia.md`](../../docs/analises/ANALISE-14-KAM-131-gate-9-na-historia.md) A1 e A2.

So biblioteca padrao e `git`, pela mesma razao que o resto do `scan_secrets`: o
*job* do gate 9 nao instala dependencias.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
from pathlib import Path

from .scanner import (
    BINARIOS,
    Achado,
    ConfiguracaoInvalida,
    Permissoes,
    varrer_texto,
)

#: O que se escreve quando um blob nao tem commit atribuido. Acontece quando so
#: a travessia por objectos o alcanca — um merge que introduz conteudo proprio.
SEM_COMMIT = "(sem atribuicao a commit)"


# ---------------------------------------------------------------------------
# O modo de accionamento
# ---------------------------------------------------------------------------

#: O que cada accionamento faz **quando nao ha intervalo**. Esta escrito aqui, e
#: nao deixado ao caso, porque e isso que o criterio de aceitacao 5 pede: a
#: escolha entre falhar e varrer so a arvore e por modo.
#:
#: `None` = fail-closed: o gate fica vermelho. E o caso do `pull_request`, que e
#: o unico accionamento que decide um merge: um PR sem SHA de base e um
#: *workflow* quebrado, e um gate que nao sabe o que varrer nao pode dar
#: passagem.
#:
#: Uma cadeia = varre-se so a arvore, **e diz-se**. Nenhum destes decide um
#: merge, e em nenhum deles existe intervalo para varrer:
#:   `push` com `before` a zeros  o ramo acabou de nascer: nao ha estado anterior
#:   `workflow_dispatch`          reexecucao a mao: o evento nao traz intervalo
#:   `schedule`                   o mesmo, sem ninguem a carregar no botao
#:   `""` (sem accionamento)      execucao local (`make ci-9` na maquina de quem
#:                                desenvolve), onde nao existe PR
SEM_INTERVALO: dict[str, str | None] = {
    "pull_request": None,
    "pull_request_target": None,
    "merge_group": None,
    "push": "`push` com `before` a zeros: o ramo nasceu neste evento e nao ha estado anterior",
    "workflow_dispatch": "reexecucao a mao: o accionamento nao traz intervalo",
    "schedule": "tarefa agendada: o accionamento nao traz intervalo",
    "": "execucao local: GATE9_BASE nao esta definido e nao existe PR",
}


def _ausente(valor: str | None) -> bool:
    """Vazio, ou so zeros — que e o `before` que o GitHub poe num ramo novo."""
    if valor is None:
        return True
    limpo = valor.strip()
    return not limpo or set(limpo) == {"0"}


@dataclasses.dataclass(frozen=True)
class Intervalo:
    #: `historia` (ha intervalo) ou `so-arvore` (nao ha, e diz-se qual a razao).
    modo: str
    base: str = ""
    head: str = ""
    razao: str = ""


def decidir_intervalo(evento: str | None, base: str | None, head: str | None) -> Intervalo:
    """O intervalo a varrer, ou o modo em que se corre quando nao existe.

    Funcao pura: o *workflow* passa os valores em bruto do evento e **nao
    decide nada**. E deliberado — nao ha *lint* de *workflows* neste
    repositorio, pelo que uma condicao escrita em YAML nao e verificavel por
    teste nenhum; escrita aqui, e.
    """
    if not _ausente(base):
        if _ausente(head):
            raise ConfiguracaoInvalida(
                "ha SHA de base e nao ha SHA de cabeca: o intervalo fica a meio.\n"
                "    Passe `--head` (no CI, `github.sha`)."
            )
        assert base is not None and head is not None
        return Intervalo("historia", base.strip(), head.strip())

    nome = (evento or "").strip()
    if nome not in SEM_INTERVALO:
        raise ConfiguracaoInvalida(
            f"accionamento {nome!r} sem SHA de base, e o que fazer neste "
            "accionamento nao esta escrito.\n"
            "    O gate fica vermelho de proposito: a escolha entre falhar e "
            "varrer so a arvore\n"
            "    decide-se no ticket e escreve-se em `SEM_INTERVALO`, nao se "
            "deixa ao caso.\n"
            f"    Accionamentos escritos: {', '.join(sorted(k or '(local)' for k in SEM_INTERVALO))}."
        )

    razao = SEM_INTERVALO[nome]
    if razao is None:
        raise ConfiguracaoInvalida(
            f"accionamento {nome!r} sem SHA de base.\n"
            "    Este accionamento decide um merge, pelo que a passagem da "
            "historia e obrigatoria.\n"
            "    No CI o valor e `github.event.pull_request.base.sha`; se chega "
            "vazio, o job esta quebrado.\n"
            "    Um gate que nao sabe o que varrer nao da passagem."
        )
    return Intervalo("so-arvore", razao=razao)


# ---------------------------------------------------------------------------
# Plumbing do git
# ---------------------------------------------------------------------------


def _git(raiz: Path, *argumentos: str) -> str:
    try:
        resultado = subprocess.run(
            ["git", *argumentos], cwd=raiz, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as excepcao:
        erro = getattr(excepcao, "stderr", b"") or b""
        detalhe = erro.decode("utf-8", "replace").strip() or str(excepcao)
        raise ConfiguracaoInvalida(
            f"`git {' '.join(argumentos)}` falhou em {raiz}: {detalhe}"
        ) from excepcao
    return resultado.stdout.decode("utf-8", "replace")


def _recusar_clone_raso(raiz: Path) -> None:
    """Um clone raso nao tem o intervalo, e **nao** se varre pela metade.

    E o modo de falha que o criterio de aceitacao 4 nomeia: o `actions/checkout`
    traz um so commit por omissao, e nesse clone a travessia devolveria um
    conjunto pequeno e um gate verde.
    """
    if _git(raiz, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise ConfiguracaoInvalida(
            "o clone e raso (*shallow*) e nao tem a historia do intervalo.\n"
            "    Ponha `fetch-depth: 0` no `actions/checkout` do job do gate 9.\n"
            "    Varrer um intervalo truncado daria um verde que nao significa nada."
        )


def _resolver(raiz: Path, referencia: str, papel: str) -> str:
    try:
        return _git(
            raiz, "rev-parse", "--verify", "--quiet", f"{referencia}^{{commit}}"
        ).strip()
    except ConfiguracaoInvalida as excepcao:
        raise ConfiguracaoInvalida(
            f"{papel} ({referencia!r}) nao existe neste clone.\n"
            "    E quase sempre a profundidade do checkout: com `fetch-depth` a 1\n"
            "    o SHA de base do PR nem chega ao clone. Ponha `fetch-depth: 0`.\n"
            "    Um intervalo que nao se resolve e um gate vermelho, nunca uma\n"
            "    passagem em silencio."
        ) from excepcao


def _objectos_do_intervalo(raiz: Path, base: str, head: str) -> tuple[list[str], dict[str, str]]:
    """Os commits do intervalo, e `sha -> caminho` de todo o objecto nomeado.

    `git rev-list --objects` imprime o commit **sozinho** na linha e os restantes
    objectos com o caminho em que a travessia os encontrou — a arvore de raiz
    com o caminho vazio. Sai tudo da mesma invocacao: e o conjunto **completo**
    do intervalo, e e por isso que esta travessia existe ao lado da outra.
    """
    saida = _git(raiz, "rev-list", "--objects", f"{base}..{head}")
    commits: list[str] = []
    pares: dict[str, str] = {}
    for linha in saida.splitlines():
        sha, separador, caminho = linha.partition(" ")
        if not separador:
            commits.append(sha)
        elif caminho:
            pares.setdefault(sha, caminho)
    return commits, pares


#: Um SHA completo. Serve para distinguir, na saida do `git log -z`, o cabecalho
#: de um commit dos registos de diff.
_SHA = re.compile(r"[0-9a-f]{40,64}")


def _introduzidos(raiz: Path, base: str, head: str) -> dict[str, set[tuple[str, str]]]:
    """`sha do blob -> {(commit, caminho)}` em que o blob entrou.

    Uma invocacao para o intervalo inteiro, e nao uma por commit: um PR de 40
    commits custava 40 processos, e num `git` de Windows isso sozinho eram
    dezenas de segundos.

    **`-c` e nao `-m`.** Com `-m`, numa cabeca que seja o *merge commit* de teste
    do PR, o diff contra cada pai arrastaria tudo o que o `main` ganhou desde a
    bifurcacao — o `main` inteiro, que o criterio de aceitacao 3 proibe. Com `-c`,
    um merge leva so os caminhos que diferem de **todos** os pais: nada num merge
    limpo, e o que ele introduza por si quando o houver. Sem nenhum dos dois, o
    `git log --raw` nao imprime sequer o cabecalho de um merge — e era por ai que
    passava a evasao que a revisao adversarial construiu (A1, A2).

    `--no-renames` desliga a deteccao de mudancas de nome, cujos registos levam
    **dois** caminhos: com ela, uma mudanca de nome descalibrava a leitura de
    todos os registos seguintes e o blob perdia a atribuicao a commit. Sem ela, a
    mudanca de nome aparece como um apagar e um acrescentar, e e o acrescentar
    que interessa.
    """
    saida = _git(
        raiz,
        "log",
        "--raw",
        "-z",
        "-c",
        "--no-abbrev",
        "--no-renames",
        "--diff-filter=d",
        "--root",
        "--format=%H",
        f"{base}..{head}",
    )
    atribuicao: dict[str, set[tuple[str, str]]] = {}
    campos = saida.split("\0")
    commit = ""
    indice = 0
    while indice < len(campos):
        campo = campos[indice].strip()
        if campo.startswith(":"):
            # Um registo normal tem um `:`; um registo combinado (merge) tem um
            # por pai. Com N dois-pontos ha N+1 modos, N SHA de origem, o SHA de
            # destino e o estado — pelo que o de destino esta sempre em 2N+1,
            # contando o `:` colado ao primeiro modo.
            #
            #   `:100644 100644 <sha a> <sha b> M`             N = 1 -> indice 3
            #   `::000000 000000 100644 <a> <b> <dst> AA`       N = 2 -> indice 5
            pais = len(campo) - len(campo.lstrip(":"))
            partes = campo.split(" ")
            caminho = campos[indice + 1] if indice + 1 < len(campos) else ""
            indice += 2
            if commit and caminho and len(partes) >= 2 * pais + 3:
                sha_novo = partes[2 * pais + 1]
                if sha_novo and set(sha_novo) != {"0"}:
                    atribuicao.setdefault(sha_novo, set()).add((commit, caminho))
            continue
        if _SHA.fullmatch(campo):
            commit = campo
        indice += 1
    return atribuicao


def _tipos(raiz: Path, shas: list[str]) -> dict[str, str]:
    """O tipo de cada objecto, numa so invocacao do `git`."""
    if not shas:
        return {}
    entrada = ("\n".join(shas) + "\n").encode()
    processo = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        cwd=raiz,
        input=entrada,
        capture_output=True,
    )
    if processo.returncode != 0:
        detalhe = processo.stderr.decode("utf-8", "replace").strip()
        raise ConfiguracaoInvalida(f"`git cat-file --batch-check` falhou: {detalhe}")
    tipos: dict[str, str] = {}
    for linha in processo.stdout.decode("utf-8", "replace").splitlines():
        campos = linha.split()
        if len(campos) >= 2:
            tipos[campos[0]] = campos[1]
    return tipos


def _conteudos(raiz: Path, shas: list[str]) -> dict[str, bytes]:
    """O conteudo de cada blob, numa so invocacao do `git`. Uma leitura por SHA."""
    if not shas:
        return {}
    entrada = ("\n".join(shas) + "\n").encode()
    processo = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=raiz,
        input=entrada,
        capture_output=True,
    )
    if processo.returncode != 0:
        detalhe = processo.stderr.decode("utf-8", "replace").strip()
        raise ConfiguracaoInvalida(f"`git cat-file --batch` falhou: {detalhe}")
    dados = processo.stdout
    conteudos: dict[str, bytes] = {}
    posicao = 0
    while posicao < len(dados):
        fim = dados.find(b"\n", posicao)
        if fim < 0:
            break
        cabecalho = dados[posicao:fim].decode("utf-8", "replace").split()
        posicao = fim + 1
        if len(cabecalho) < 3 or not cabecalho[2].isdigit():
            # `<sha> missing` — nao ha conteudo a seguir.
            continue
        tamanho = int(cabecalho[2])
        conteudos[cabecalho[0]] = dados[posicao : posicao + tamanho]
        posicao += tamanho + 1
    return conteudos


# ---------------------------------------------------------------------------
# O varrimento
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AchadoNaHistoria:
    """Um achado, com o commit e o caminho em que o blob apareceu.

    Nao leva o valor: a amostra do `Achado` sao quatro caracteres e o
    comprimento, como na passagem da arvore.
    """

    achado: Achado
    commit: str
    blob: str

    def __str__(self) -> str:
        # O commit **nao** se trunca quando nao e um SHA: `SEM_COMMIT[:12]` dava
        # `(sem atrib`, um fragmento sem sentido no campo de que a correccao
        # depende. Achado A7 da revisao adversarial.
        curto = self.commit[:12] if _SHA.fullmatch(self.commit) else self.commit
        return f"{curto} {self.achado}\n    blob {self.blob[:12]}"


@dataclasses.dataclass(frozen=True)
class Resultado:
    """O que a passagem fez — e o que **nao** fez.

    Os contadores do que se saltou existem porque a primeira versao somava os
    *bytes* antes de descodificar e contava os blobs que *pretendia* ler: dizia
    «1 blob novo, 73 bytes lidos, limpo» sobre um ficheiro que nao tinha
    varrido. E o mesmo defeito que `scanner.py` conta em `_fragmentos` («nao se
    varre, **e diz-se**» — e nao se dizia nada), repetido. Achado A4.
    """

    commits: int
    blobs_varridos: int
    bytes_varridos: int
    saltados_por_extensao: int
    nao_decifraveis: int
    #: Blobs que a travessia por objectos alcancou e que nenhum registo de diff
    #: atribuiu. Depois do `-c` isto deve ser sempre zero; conta-se para que
    #: deixe de o ser em voz alta. Ver `_locais_por_blob`.
    sem_atribuicao: int
    achados: tuple[AchadoNaHistoria, ...]

    @property
    def onde(self) -> str:
        partes = [
            f"{self.blobs_varridos} blob(s) varrido(s) em {self.commits} "
            f"commit(s) do intervalo ({self.bytes_varridos} bytes)"
        ]
        if self.saltados_por_extensao:
            partes.append(
                f"{self.saltados_por_extensao} blob(s) NAO varrido(s) por "
                "extensao de binario"
            )
        if self.nao_decifraveis:
            partes.append(
                f"{self.nao_decifraveis} blob(s) NAO varrido(s) por nao serem "
                "texto UTF-8"
            )
        if self.sem_atribuicao:
            partes.append(
                f"{self.sem_atribuicao} blob(s) sem registo de diff que os "
                "atribua a um commit"
            )
        return "; ".join(partes)


def _locais_por_blob(
    blobs: list[str],
    atribuicao: dict[str, set[tuple[str, str]]],
    pares: dict[str, str],
) -> dict[str, dict[str, str]]:
    """`sha -> {caminho: commit}` — todos os caminhos em que o blob entrou.

    Sao **todos** e nao um: o mesmo blob pode entrar na pasta do canario (onde
    uma chave com forma real e permitida) e noutro caminho qualquer, e nesse
    caso tem de ser achado. A deduplicacao e por SHA no que custa — a leitura e
    o casamento dos padroes —, nunca na aplicacao das areas permitidas. Foi
    assim que a revisao adversarial pos o gate verde (A1): o comentario dizia
    isto e o codigo aplicava a area de **um** caminho.

    O recurso ao caminho do `rev-list` e o `<blob …>` sao a ultima linha: depois
    do `-c`, nao se conhece caso em que um blob do intervalo nao tenha registo
    de diff, e por isso **nao tem teste nem mutacao** — uma mutacao que nenhum
    teste apanha seria uma sobrevivente. O que se faz em vez disso e contar:
    `Resultado.sem_atribuicao` chega ao relatorio, para que o dia em que isto
    acontecer seja visivel em vez de silencioso.
    """
    locais: dict[str, dict[str, str]] = {}
    for sha in blobs:
        por_caminho: dict[str, str] = {}
        for commit, caminho in sorted(atribuicao.get(sha, set())):
            por_caminho.setdefault(caminho, commit)
        if sha in pares:
            por_caminho.setdefault(pares[sha], SEM_COMMIT)
        if not por_caminho:
            por_caminho[f"<blob {sha[:12]}>"] = SEM_COMMIT
        locais[sha] = por_caminho
    return locais


def varrer_intervalo(
    raiz: Path, base: str, head: str, permissoes: Permissoes
) -> Resultado:
    """Os blobs que `base..head` acrescenta, varridos uma vez cada."""
    _recusar_clone_raso(raiz)
    base_sha = _resolver(raiz, base, "o SHA de base")
    head_sha = _resolver(raiz, head, "o SHA de cabeca")

    commits, pares = _objectos_do_intervalo(raiz, base_sha, head_sha)
    atribuicao = _introduzidos(raiz, base_sha, head_sha)

    candidatos = sorted(set(pares) | set(atribuicao))
    tipos = _tipos(raiz, candidatos)
    blobs = [sha for sha in candidatos if tipos.get(sha) == "blob"]
    locais = _locais_por_blob(blobs, atribuicao, pares)

    # Binarios e artefactos nao se varrem, pela mesma regra da passagem da
    # arvore. O blob so se descarta quando **nenhum** dos seus caminhos e de
    # texto: o mesmo conteudo com dois nomes nao se dispensa pelo nome mais
    # conveniente.
    de_texto = {
        sha: {
            caminho: commit
            for caminho, commit in por_caminho.items()
            if Path(caminho).suffix.lower() not in BINARIOS
        }
        for sha, por_caminho in locais.items()
    }
    a_ler = [sha for sha in blobs if de_texto[sha]]
    conteudos = _conteudos(raiz, a_ler)

    achados: list[AchadoNaHistoria] = []
    bytes_varridos = 0
    varridos = 0
    nao_decifraveis = 0
    sem_areas = permissoes.sem_areas()
    for sha in a_ler:
        bruto = conteudos.get(sha)
        if bruto is None:
            # O objecto esta no intervalo e o `git` nao o deu. Nao se conta como
            # limpo: um blob que se devia varrer e nao se leu e um gate que nao
            # sabe o que esta a dizer.
            raise ConfiguracaoInvalida(
                f"o objecto {sha[:12]} esta no intervalo e o `git cat-file` nao "
                "o devolveu.\n"
                "    Um blob que se devia varrer e nao se leu nao pode contar "
                "como limpo."
            )
        try:
            texto = bruto.decode("utf-8")
        except UnicodeDecodeError:
            nao_decifraveis += 1
            continue
        varridos += 1
        bytes_varridos += len(bruto)
        # Uma leitura e um casamento de padroes por SHA. As areas permitidas
        # aplicam-se depois, com o caminho que o blob tinha **nesse commit**.
        brutos = varrer_texto(texto, "", sem_areas)
        if not brutos:
            continue
        for caminho, commit in sorted(de_texto[sha].items()):
            permitidas = permissoes.classes_permitidas(caminho)
            for achado in brutos:
                if achado.classe in permitidas:
                    continue
                achados.append(
                    AchadoNaHistoria(
                        achado=dataclasses.replace(achado, ficheiro=caminho),
                        commit=commit,
                        blob=sha,
                    )
                )

    return Resultado(
        commits=len(commits),
        blobs_varridos=varridos,
        bytes_varridos=bytes_varridos,
        saltados_por_extensao=len(blobs) - len(a_ler),
        nao_decifraveis=nao_decifraveis,
        sem_atribuicao=sum(1 for sha in blobs if sha not in atribuicao),
        achados=tuple(achados),
    )


#: Accionamentos em que um intervalo **sem commits** e configuracao quebrada, e
#: nao um PR sem novidades: a cabeca e o *merge commit* de teste, que e novo por
#: construcao. Zero commits ali significa que a base e a cabeca vieram trocadas
#: ou iguais — e foi assim que a revisao adversarial pos o gate a nao varrer
#: nada e a dizer-se limpo, trocando duas linhas do YAML sem nenhum teste
#: falhar (A3).
EXIGEM_COMMITS = frozenset({"pull_request", "pull_request_target", "merge_group"})


def exigir_commits(evento: str | None, commits: int) -> None:
    """Num accionamento que decide um merge, um intervalo vazio e erro."""
    if commits:
        return
    nome = (evento or "").strip()
    if nome not in EXIGEM_COMMITS:
        return
    raise ConfiguracaoInvalida(
        f"accionamento {nome!r} com um intervalo de **zero** commits.\n"
        "    A cabeca de um PR e o *merge commit* de teste, que e novo por "
        "construcao:\n"
        "    zero commits significa que a base e a cabeca vieram trocadas, ou "
        "iguais.\n"
        "    Um gate que nao varreu nada nao se diz limpo."
    )
