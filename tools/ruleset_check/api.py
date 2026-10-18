"""Obtencao do ruleset efectivo. **So leitura.**

Nao existe neste modulo — nem em nenhum outro do pacote — uma chamada `POST`,
`PUT`, `PATCH` ou `DELETE`. E deliberado e tem teste
(`tests/test_api_e_cli.py::TestSemCaminhoDeEscrita`): a decisao do
`docs/adr/ADR-L003-verificacao-do-ruleset.md` e «so deteccao», e um caminho de
escrita aqui tornava a credencial de leitura numa credencial de escrita a espera
de ser trocada.

Dois transportes, pela razao que o ADR escreve:

* **`gh`** (por omissao) — o valor do token nunca passa por este codigo nem pelo
  ambiente: vive no porta-chaves do `gh` de quem opera. E o caminho do
  `make ruleset`, e o mesmo `gh api` que o `.github/rulesets/README.md` ja usa
  para reproduzir a exportacao.
* **`http`** — urllib da biblioteca padrao, com o token em `KAMBA_RULESET_TOKEN`.
  Existe para o contexto fora destas Actions, onde nao ha `gh` instalado.

**Fail-closed inclui nao conseguir verificar.** Qualquer falha — binario
ausente, rede em baixo, `401`, `403`, `404`, corpo que nao e JSON — levanta
`ApiIndisponivel`, e quem chama transforma isso em **2**. Nunca em «conforme».
E a regra que o gate 11 ja aplica a OSV.

**O token nunca entra numa mensagem de erro.** O `gh` nao o imprime, o cabecalho
`Authorization` nao e reproduzido, e ha um teste que corre o caminho de erro com
um valor sentinela e exige que ele nao apareca na saida.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request

#: O **nome** da variavel de ambiente onde o transporte `http` procura o token
#: — nao o token, que nunca aparece em codigo nenhum. Nao ha segunda: um
#: `GH_TOKEN` apanhado por acaso e uma credencial que entra sem ninguem decidir
#: que entrava.
#:
#: Chama-se `NOME_DA_VARIAVEL` e nao `VARIAVEL_DO_TOKEN` por causa do gate 9:
#: um nome que significa segredo, com um valor de entropia suficiente, e um
#: achado da classe `atribuicao` — e tinha razao em o ser, porque e assim que
#: um segredo a serio entra. O nome certo e o que descreve o que a constante
#: guarda.
NOME_DA_VARIAVEL = "KAMBA_RULESET_TOKEN"

#: Segundos. Generoso: falhar por tempo esgotado custa um falso vermelho, e um
#: falso vermelho treina quem opera a ignorar a verificacao.
ESPERA = 30

BASE = "https://api.github.com/"

TRANSPORTES = ("gh", "http")


class ApiIndisponivel(RuntimeError):
    """Nao se conseguiu ler o ruleset efectivo. Falha, nao deixa passar."""


def _sem_token(texto: str, token: str) -> str:
    """Rede de seguranca: se o valor aparecer na mensagem, sai mascarado.

    Nenhum caminho conhecido o la poe — o `gh` nao o imprime e o cabecalho nao e
    reproduzido. Isto existe porque «nenhum caminho conhecido» e exactamente o
    que se diz antes de aparecer um.
    """
    if token and token in texto:
        return texto.replace(token, "<token>")
    return texto


def obter_via_gh(caminho: str) -> dict:
    """`gh api <caminho>`. O token fica no porta-chaves do `gh`."""
    try:
        resultado = subprocess.run(
            ["gh", "api", caminho],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=ESPERA,
        )
    except FileNotFoundError as erro:
        raise ApiIndisponivel(
            "`gh` nao esta instalado ou nao esta no PATH. Instale o GitHub CLI e "
            "corra `gh auth login`, ou use `--transporte http` com "
            f"{NOME_DA_VARIAVEL}."
        ) from erro
    except subprocess.TimeoutExpired as erro:
        raise ApiIndisponivel(f"`gh api {caminho}` nao respondeu em {ESPERA}s") from erro
    if resultado.returncode != 0:
        erro_do_gh = (resultado.stderr or resultado.stdout or "").strip()
        raise ApiIndisponivel(
            f"`gh api {caminho}` saiu {resultado.returncode}: {erro_do_gh}"
        )
    try:
        dados = json.loads(resultado.stdout)
    except json.JSONDecodeError as erro:
        raise ApiIndisponivel(f"`gh api {caminho}` nao devolveu JSON: {erro}") from erro
    if not isinstance(dados, dict):
        raise ApiIndisponivel(
            f"`gh api {caminho}` devolveu {type(dados).__name__} e nao um objecto"
        )
    return dados


def obter_via_http(caminho: str, token: str) -> dict:
    """`GET https://api.github.com/<caminho>`, com o token do ambiente."""
    if not token:
        raise ApiIndisponivel(
            f"{NOME_DA_VARIAVEL} nao esta definida. O transporte `http` precisa de "
            "um token com `administration: read` "
            "(docs/adr/ADR-L003-verificacao-do-ruleset.md)."
        )
    pedido = urllib.request.Request(
        BASE + caminho.lstrip("/"),
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "kamba-ruleset-check/1",
        },
    )
    try:
        with urllib.request.urlopen(pedido, timeout=ESPERA) as resposta:
            bruto = resposta.read().decode("utf-8")
    except urllib.error.HTTPError as erro:
        raise ApiIndisponivel(
            _sem_token(f"GET {caminho}: {erro.code} {erro.reason}", token)
        ) from erro
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        raise ApiIndisponivel(_sem_token(f"GET {caminho}: {erro}", token)) from erro
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError as erro:
        raise ApiIndisponivel(f"GET {caminho} nao devolveu JSON: {erro}") from erro
    if not isinstance(dados, dict):
        raise ApiIndisponivel(f"GET {caminho} devolveu {type(dados).__name__}")
    return dados


def obter(caminho: str, transporte: str = "gh") -> dict:
    if transporte == "gh":
        return obter_via_gh(caminho)
    if transporte == "http":
        return obter_via_http(caminho, os.environ.get(NOME_DA_VARIAVEL, ""))
    raise ValueError(f"transporte desconhecido {transporte!r}; e um de {TRANSPORTES}")
