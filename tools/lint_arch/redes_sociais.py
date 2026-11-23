"""Nenhuma publicacao em redes sociais no repositorio (KAM-122, criterio 7).

O criterio 7 do bloco pede um teste de CI que garanta **zero** referencias aos
tres caminhos de publicacao da Graph API que o bloco nomeia, e **zero** variaveis
ou segredos de *tokens* de redes, no repositorio e na configuracao. A publicacao por API esta
**Diferida** (D13): o dono publica a mao, e o `SocialPublisher` so tem a
`ManualDelivery`, cujo `publish()` lanca `NotEnabled`.

## O que se procura

Em **todo** o ficheiro seguido pelo `git` (`git ls-files`, e nao o disco: o
disco de um *worktree* ve os irmaos), excepto os `.md`:

  caminhos     os segmentos da Graph API que publicam (o de publicar media, o
               do mural de uma pagina e o das fotografias) e os anfitrioes que
               so servem redes (o do Instagram e o do TikTok). O anfitriao da
               Graph API do Facebook **nao** esta aqui: e o da Cloud API do
               WhatsApp, e o Outbound usa-o.
  permissoes   os *scopes* de publicacao de paginas, do Instagram e de grupos.
  segredos     um identificador (maiusculas ou minusculas, partido por `_`,
               `-` ou `.`) com um segmento de rede (INSTAGRAM, FACEBOOK,
               TIKTOK, THREADS, IG, FB, ou PAGE com ACCESS ou META) e um
               segmento TOKEN, SECRET ou KEY. Le-se **por segmentos** e nao por
               subcadeia: `CONFIG_TOKEN` tem «IG» la dentro e nao e de rede. O
               segredo da Meta do WhatsApp (`META_ACCESS_TOKEN`) nao casa: nao
               nomeia uma rede social nem uma pagina.

## O que esta varredura nao apanha, e fica dito

E um *lint* de texto, e nao uma prova: uma cadeia partida em pedacos no codigo
(como este proprio ficheiro faz) passa, e um nome inventado que nao nomeie a
rede tambem. O que ele fecha e o descuido; a ausencia de publicacao e tambem
do desenho (so a `ManualDelivery` existe, e o `publish()` lanca `NotEnabled`).

## Porque os `.md` ficam de fora, e o que isso nao esconde

Os documentos **descrevem** a proibicao — o bloco do KAM-122 cita os tres
caminhos para os proibir, e o `E5` descreve a API de publicacao. Um documento nao
publica nada. O codigo, a configuracao, os *yaml*, os `.env.example` e os
*compose* ficam todos dentro.

**Este ficheiro e o ensaio dele nao se excluem**: os padroes estao escritos por
partes, de modo que nenhum dos dois contem o texto que procura. Excluir o
proprio ficheiro abria um sitio onde a cadeia proibida podia viver.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

#: Os padroes, **por partes**: o texto inteiro nao aparece neste ficheiro.
_MEDIA = "media" + "_" + "publish"
#: Os segmentos que nomeiam uma rede social num identificador (achado 5 da revisao).
_SEGMENTOS_DE_REDE = frozenset({"INSTAGRAM", "FACEBOOK", "TIKTOK", "THREADS", "IG", "FB"})
#: Os segmentos de um segredo.
_SEGMENTOS_DE_SEGREDO = frozenset({"TOK" "EN", "SEC" "RET", "KEY"})
_IDENTIFICADOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*[A-Za-z0-9]")


def _e_segredo_de_rede(identificador: str) -> bool:
    segmentos = set(re.split(r"[_.-]", identificador.upper()))
    if not segmentos & _SEGMENTOS_DE_SEGREDO:
        return False
    if segmentos & _SEGMENTOS_DE_REDE:
        return True
    # Uma pagina de rede: o de acesso a pagina, ou o da pagina da Meta.
    return "PAGE" in segmentos and bool(segmentos & {"ACCESS", "META"})


PADROES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("caminho de publicacao", re.compile(_MEDIA)),
    ("caminho de publicacao", re.compile(r"/(?:fe" r"ed|pho" r"tos|vid" r"eos|live_vid" r"eos)\b|_sto" r"ries\b")),
    ("anfitriao de rede", re.compile(r"graph\.insta" r"gram\.com|tiktok" r"apis|rupl" r"oad\.facebook")),
    (
        "permissao de publicacao",
        re.compile(
            r"pages_manage_" r"posts|instagram(?:_business)?_content_" r"publish"
            r"|threads_content_" r"publish|publish_to_" r"groups|publish_" r"video|publish_" r"actions"
        ),
    ),
)

#: Os documentos descrevem a proibicao (ver a nota do modulo).
EXCLUIDOS = (".md",)

#: Binarios que o `git` segue e que nao se leem como texto.
BINARIOS = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".ttf", ".otf", ".zip")


def _do_git(root: Path) -> list[str]:
    """Os ficheiros seguidos. **Falha fechada**: sem `git` nao ha varredura."""
    saida = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if saida.returncode != 0:
        raise RuntimeError(
            f"`git ls-files` saiu com {saida.returncode} em {root}: varrer zero ficheiros "
            "reportava conforme"
        )
    return [linha for linha in saida.stdout.splitlines() if linha]


def achados_no_texto(caminho: str, texto: str) -> list[str]:
    """Os achados de um ficheiro, `caminho:linha: tipo`."""
    achados: list[str] = []
    for numero, linha in enumerate(texto.splitlines(), start=1):
        for tipo, padrao in PADROES:
            if padrao.search(linha):
                achados.append(f"{caminho}:{numero}: {tipo}")
        if any(_e_segredo_de_rede(i) for i in _IDENTIFICADOR.findall(linha)):
            achados.append(f"{caminho}:{numero}: segredo de rede")
    return achados


def check(root: Path, caminhos: list[str] | None = None) -> list[str]:
    """Os achados na arvore seguida (ou nos `caminhos` dados, para os ensaios)."""
    achados: list[str] = []
    for relativo in caminhos if caminhos is not None else _do_git(root):
        if relativo.lower().endswith(EXCLUIDOS + BINARIOS):
            continue
        ficheiro = root / relativo
        if not ficheiro.is_file():
            continue
        try:
            texto = ficheiro.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        achados.extend(achados_no_texto(relativo, texto))
    return achados
