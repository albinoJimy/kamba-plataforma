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
  segredos     um nome de variavel em maiusculas com uma rede e um TOKEN, SECRET
               ou KEY. O segredo da Meta do WhatsApp nao casa: o nome dele nao
               nomeia uma rede social.

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
_REDES = "INSTAGRAM|FACEBOOK|FB_PAGE|PAGE_ACCESS|TIKTOK"

PADROES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("caminho de publicacao", re.compile(_MEDIA)),
    ("caminho de publicacao", re.compile(r"/(?:fe" r"ed|pho" r"tos)\b")),
    ("anfitriao de rede", re.compile(r"graph\.insta" r"gram\.com|tiktok" r"apis")),
    (
        "permissao de publicacao",
        re.compile(
            r"pages_manage_" r"posts|instagram(?:_business)?_content_" r"publish"
            r"|publish_to_" r"groups|publish_" r"video"
        ),
    ),
    (
        "segredo de rede",
        re.compile(r"\b[A-Z0-9_]*(?:" + _REDES + r")[A-Z0-9_]*(?:TOK" r"EN|SEC" r"RET|KEY)[A-Z0-9_]*\b"),
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
