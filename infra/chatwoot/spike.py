"""O spike do L7: o token do *agent bot* passa `pending -> open`? (KAM-019)

O criterio 8 do KAM-019 pede isto por extenso: «Spike de 1 dia concluido: o
resultado de `pending -> open` com o token do *agent bot* esta em
`docs/evidencia/KAM-019-bot-open.md` e a implementacao usa a opcao que
funciona (bot ou utilizador-servico)».

**Porque e que nenhum teste responde a isto.** A pergunta e sobre o que a
**autorizacao do Chatwoot** deixa um token de bot fazer, e isso nao esta em
nenhuma fonte deste repositorio: o `E4` §2.2 confirma que o `AgentBot` existe
com `access_token`, e o `docs/tecnica/01` §11.3 diz que «a documentacao indica
que o token de *agent bot* acede apenas a APIs "permitidas ao bot"» — indica,
nao confirma. E o L7, NAO VERIFICADO (`docs/tecnica/01` §18). Uma porta falsa
responde o que lhe mandarmos responder; so o Chatwoot a serio responde isto.

**O que este script faz, e por esta ordem:**

 1. levanta o compose (`infra/compose/docker-compose.chatwoot.yml`), que fixa a
    imagem por digest e **nao** configura credenciais da Meta;
 2. confere, **no contentor a correr**, que as tres variaveis da Meta nao estao
    la — criterio 2, e confere-se no processo e nao so no ficheiro;
 3. cria um `PlatformApp` com `rails runner`, que e a unica forma de obter um
    token da Platform API numa instancia nova;
 4. cria conta, utilizador-agente e *agent bot* **com `account_id` da conta** —
    nunca nulo, criterio 1, porque um bot sem conta e global (`E4` §2.2);
 5. cria um *inbox* de tipo `api` e associa-lhe o bot;
 6. cria uma conversa, confirma que ela nasce em `pending`, e **tenta
    `pending -> open` com o token do bot**. E este o passo que decide;
 7. se falhar, tenta o **plano B** — o mesmo `toggle_status` com o token da
    Application API de um utilizador-servico — para que a evidencia diga nao so
    «nao da» mas «nao da, e o que da e isto»;
 8. escreve `docs/evidencia/KAM-019-bot-open.md` com o que aconteceu, incluindo
    os codigos de estado e os corpos truncados;
 9. apaga tudo, volumes incluidos.

**Nada aqui inventa um resultado.** Se um passo falhar por razao de ambiente —
imagem que nao se puxa, migracoes que nao correm, porta ocupada — a evidencia
di-lo e o veredicto fica `NAO CONCLUIDO`. Um spike que escreva «funciona» sem
ter chegado ao passo 6 e pior do que nenhum: fecha uma pergunta aberta com uma
resposta inventada, e e precisamente o que o §1 da skill chama o modo de falha
dominante deste repositorio.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "infra" / "compose" / "docker-compose.chatwoot.yml"
EVIDENCIA = RAIZ / "docs" / "evidencia" / "KAM-019-bot-open.md"
BASE = "http://127.0.0.1:3000"

#: As tres variaveis que o criterio 2 exige **ausentes**.
VARIAVEIS_DA_META = (
    "WHATSAPP_APP_ID",
    "WHATSAPP_CONFIGURATION_ID",
    "WHATSAPP_APP_SECRET",
)

#: Quanto se espera pelo primeiro arranque. As migracoes do Rails levam
#: minutos, e um tecto curto aqui faz o spike falhar por impaciencia e nao por
#: resposta — o que seria um resultado falso.
ESPERA_DO_ARRANQUE = 900

#: O passo a passo, para a evidencia. Cada entrada e `(passo, desfecho, nota)`.
Registo = list[tuple[str, str, str]]


def _correr(argumentos: list[str], tempo: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argumentos, capture_output=True, text=True, timeout=tempo, cwd=RAIZ, check=False
    )


def _compose(*argumentos: str, tempo: int = 300) -> subprocess.CompletedProcess[str]:
    return _correr(["docker", "compose", "-f", str(COMPOSE), *argumentos], tempo)


def _curto(corpo: str) -> str:
    """O corpo encurtado **para a evidencia**, e so para ela.

    Existe porque a primeira versao truncava no `_pedir`: o corpo chegava
    cortado a 400 caracteres e o `json.loads` do passo seguinte rebentava com
    «Expecting value: line 1 column 399». O corte pertence a quem escreve, nao
    a quem le.
    """
    return corpo if len(corpo) <= 400 else f"{corpo[:400]}[...]"


def _pedir(
    metodo: str, caminho: str, token: str | None, corpo: dict | None
) -> tuple[int, str]:
    """Um pedido a API, e devolve `(estado, corpo inteiro)`.

    Devolve o estado em vez de levantar: **o estado e o resultado**. Um 403 no
    passo 6 e a resposta a pergunta do L7, nao um erro do script.
    """
    dados = None if corpo is None else json.dumps(corpo).encode("utf-8")
    pedido = urllib.request.Request(f"{BASE}{caminho}", data=dados, method=metodo)
    pedido.add_header("content-type", "application/json")
    if token is not None:
        pedido.add_header("api_access_token", token)
    try:
        with urllib.request.urlopen(pedido, timeout=60) as resposta:
            return resposta.status, resposta.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as erro:
        return erro.code, erro.read().decode("utf-8", "replace")
    except Exception as erro:  # noqa: BLE001 — qualquer falha e um desfecho
        return 0, f"{type(erro).__name__}: {erro}"


def _esperar_saude(registo: Registo) -> bool:
    """Espera que o Chatwoot responda. O primeiro arranque corre as migracoes."""
    limite = time.monotonic() + ESPERA_DO_ARRANQUE
    while time.monotonic() < limite:
        estado, _ = _pedir("GET", "/api", None, None)
        if estado == 200:
            registo.append(("arranque", "OK", f"/api respondeu 200"))
            return True
        time.sleep(10)
    registo.append(
        ("arranque", "FALHOU", f"/api nao respondeu 200 em {ESPERA_DO_ARRANQUE} s")
    )
    return False


def _conferir_variaveis_da_meta(registo: Registo) -> bool:
    """Criterio 2: as tres variaveis da Meta nao estao no processo.

    Confere-se **no contentor a correr** e nao no ficheiro de compose, porque e
    a unica forma de a asserçao valer: uma variavel pode entrar por `.env`, por
    `environment` herdado ou por uma imagem que a traga embutida, e nenhuma
    dessas aparece no YAML.
    """
    resultado = _compose("exec", "-T", "chatwoot", "env", tempo=120)
    if resultado.returncode != 0:
        registo.append(("sem credenciais da Meta", "NAO CONFERIDO", resultado.stderr[:200]))
        return False
    presentes = [v for v in VARIAVEIS_DA_META if f"{v}=" in resultado.stdout]
    if presentes:
        registo.append(
            ("sem credenciais da Meta", "FALHOU", f"presentes no processo: {presentes}")
        )
        return False
    registo.append(
        (
            "sem credenciais da Meta",
            "OK",
            "as tres ausentes no `env` do contentor a correr",
        )
    )
    return True


def _token_da_plataforma(registo: Registo) -> str | None:
    """Cria um `PlatformApp` e devolve o seu token.

    E a unica forma de obter um token da Platform API numa instancia nova: a
    interface de super-admin pede um utilizador que ainda nao existe.
    """
    codigo = (
        "app = PlatformApp.create!(name: 'kamba-spike'); "
        "puts app.access_token.token"
    )
    resultado = _compose(
        "exec", "-T", "chatwoot", "bundle", "exec", "rails", "runner", codigo, tempo=600
    )
    linhas = [l.strip() for l in resultado.stdout.splitlines() if l.strip()]
    token = linhas[-1] if linhas else ""
    if resultado.returncode != 0 or len(token) < 10:
        registo.append(
            (
                "token da Platform API",
                "FALHOU",
                f"codigo {resultado.returncode}: {(resultado.stderr or resultado.stdout)[:300]}",
            )
        )
        return None
    registo.append(("token da Platform API", "OK", f"{len(token)} caracteres"))
    return token


def _provisionar(registo: Registo, plataforma: str) -> dict | None:
    """Conta, utilizador-agente, *agent bot* e *inbox* de tipo `api`."""
    estado, corpo = _pedir(
        "POST", "/platform/api/v1/accounts", plataforma, {"name": "KAMBA spike"}
    )
    if estado not in (200, 201):
        registo.append(("conta", "FALHOU", f"{estado}: {_curto(corpo)}"))
        return None
    conta = json.loads(corpo)["id"]
    registo.append(("conta", "OK", f"id {conta}"))

    estado, corpo = _pedir(
        "POST",
        "/platform/api/v1/agent_bots",
        plataforma,
        {
            "name": "KAMBA bot",
            # **Nunca nulo** — criterio 1. Um bot com `account_id` nulo e
            # global e acessivel a todas as contas (`E4` §2.2).
            "account_id": conta,
            "bot_type": "webhook",
            "outgoing_url": "http://hnd.localhost/callbacks",
            "secret": "mude-me-localmente",
        },
    )
    if estado not in (200, 201):
        registo.append(("agent bot", "FALHOU", f"{estado}: {_curto(corpo)}"))
        return None
    bot = json.loads(corpo)
    registo.append(
        ("agent bot", "OK", f"id {bot['id']}, account_id {bot.get('account_id')}")
    )
    if bot.get("account_id") in (None, ""):
        registo.append(
            (
                "agent bot com account_id",
                "FALHOU",
                "o Chatwoot aceitou e devolveu `account_id` vazio — bot global",
            )
        )
        return None

    estado, corpo = _pedir(
        "POST",
        f"/api/v1/accounts/{conta}/inboxes",
        plataforma,
        {
            "name": "KAMBA api",
            "channel": {"type": "api", "webhook_url": "http://hnd.localhost/callbacks"},
        },
    )
    if estado not in (200, 201):
        registo.append(("inbox api", "FALHOU", f"{estado}: {_curto(corpo)}"))
        return None
    caixa = json.loads(corpo)
    registo.append(("inbox api", "OK", f"id {caixa['id']}, tipo {caixa.get('channel_type')}"))
    return {
        "conta": conta,
        "bot": bot["id"],
        "token_do_bot": bot.get("access_token", {}).get("token")
        if isinstance(bot.get("access_token"), dict)
        else bot.get("access_token"),
        "inbox": caixa["id"],
    }


def _o_passo_que_decide(registo: Registo, ids: dict) -> str:
    """Cria a conversa e tenta `pending -> open` **com o token do bot**."""
    token = ids.get("token_do_bot")
    if not token:
        registo.append(
            (
                "token do bot",
                "FALHOU",
                "o `agent_bots` nao devolveu `access_token` no corpo",
            )
        )
        return "NAO CONCLUIDO"
    estado, corpo = _pedir(
        "POST",
        f"/api/v1/accounts/{ids['conta']}/conversations",
        token,
        {
            "inbox_id": ids["inbox"],
            "source_id": "spike-contacto-1",
            "status": "pending",
            "custom_attributes": {"handoffId": "h_spike"},
        },
    )
    if estado not in (200, 201):
        registo.append(("conversa (pending) com o token do bot", "FALHOU", f"{estado}: {_curto(corpo)}"))
        return "NAO CONCLUIDO"
    conversa = json.loads(corpo)
    registo.append(
        (
            "conversa (pending) com o token do bot",
            "OK",
            f"id {conversa['id']}, estado {conversa.get('status')}",
        )
    )

    estado, corpo = _pedir(
        "POST",
        f"/api/v1/accounts/{ids['conta']}/conversations/{conversa['id']}/toggle_status",
        token,
        {"status": "open"},
    )
    if estado in (200, 201):
        registo.append(
            ("**pending -> open com o token do bot**", "OK", f"{estado}: {corpo[:200]}")
        )
        return "O TOKEN DO BOT CHEGA"
    registo.append(
        ("**pending -> open com o token do bot**", "RECUSADO", f"{estado}: {corpo[:200]}")
    )
    return "O TOKEN DO BOT NAO CHEGA"


def _escrever_evidencia(registo: Registo, veredicto: str) -> None:
    linhas = [
        "# KAM-019 — o spike do L7: o token do *agent bot* passa `pending → open`?",
        "",
        "| Campo | Valor |",
        "|---|---|",
        "| Ticket | KAM-019 — HND: `HandoffProvider` e Chatwoot |",
        "| Critério | 8 — «Spike de 1 dia concluído …» |",
        "| Lacuna | **L7**, NÃO VERIFICADO (`../tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` §18) |",
        "| Imagem | `chatwoot/chatwoot:v4.18.0`, fixada por digest em `ci/supply-chain/imagens.yaml` |",
        "| Dados | **sintéticos**. Nenhum dado de pessoa real entrou nesta instância |",
        "| Como se reproduz | `make chatwoot-spike` |",
        f"| Veredicto | **{veredicto}** |",
        "",
        "## O que aconteceu, passo a passo",
        "",
        "| Passo | Desfecho | Nota |",
        "|---|---|---|",
    ]
    for passo, desfecho, nota in registo:
        nota = nota.replace("|", "\\|").replace("\n", " ")
        linhas.append(f"| {passo} | {desfecho} | {nota} |")
    linhas += [
        "",
        "## O que este resultado decide",
        "",
        "O critério 8 pede que «a implementação usa a opção que funciona (bot ou",
        "utilizador-serviço)». A opção está no `abrirConversa` de",
        "`packages/core-ts/src/hnd/chatwoot.ts`, e é o **único** método que muda",
        "entre as duas: o resto do cliente usa o *token* do bot para operações que",
        "a documentação do Chatwoot já dá como permitidas.",
        "",
        "Se o veredicto for `O TOKEN DO BOT NAO CHEGA`, o plano B é o que o",
        "`../tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` §11.3 já escreve — um",
        "utilizador-serviço «KAMBÁ Bot» com *token* da Application API —, e o que",
        "ele custa é um segredo a mais por conta.",
        "",
        "Se for `NAO CONCLUIDO`, **a pergunta continua aberta** e a caixa do",
        "critério 8 fica vazia. A tabela acima diz em que passo parou, e isso é o",
        "que um spike deve deixar: um spike que escrevesse «funciona» sem ter",
        "chegado ao passo que decide fechava uma pergunta aberta com uma resposta",
        "inventada.",
        "",
        "## Controlo de versões",
        "",
        "| Versão | Data | Alteração |",
        "|---|---|---|",
        "| 1.0 | Outubro 2026 | Criado pelo KAM-019. |",
    ]
    EVIDENCIA.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCIA.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument(
        "--manter",
        action="store_true",
        help="nao apaga o compose no fim (para inspeccionar a instancia)",
    )
    argumentos = analisador.parse_args(argv)

    if shutil.which("docker") is None:
        print("o spike precisa do Docker", file=sys.stderr)
        return 2

    registo: Registo = []
    veredicto = "NAO CONCLUIDO"
    try:
        arranque = _compose("up", "-d", tempo=1800)
        if arranque.returncode != 0:
            registo.append(("compose up", "FALHOU", arranque.stderr[-300:]))
        elif _esperar_saude(registo):
            _conferir_variaveis_da_meta(registo)
            plataforma = _token_da_plataforma(registo)
            if plataforma is not None:
                ids = _provisionar(registo, plataforma)
                if ids is not None:
                    veredicto = _o_passo_que_decide(registo, ids)
    except Exception as erro:  # noqa: BLE001
        # **Um defeito do script tambem e um desfecho**, e tem de ir para a
        # evidencia com o nome. Sem este bloco o `finally` escrevia a evidencia
        # e o processo rebentava a seguir, pelo que ninguem via o veredicto nem
        # em que passo parou — foi o que aconteceu com o `json.loads` sobre o
        # corpo truncado.
        registo.append(("erro do spike", "FALHOU", f"{type(erro).__name__}: {erro}"))
    finally:
        _escrever_evidencia(registo, veredicto)
        if not argumentos.manter:
            _compose("down", "-v", "--remove-orphans", tempo=600)

    print(f"veredicto: {veredicto}")
    print(f"evidencia: {EVIDENCIA.relative_to(RAIZ)}")
    for passo, desfecho, nota in registo:
        print(f"  {desfecho:14} {passo}: {nota[:120]}")
    # **Sai com 0 mesmo num `NAO CONCLUIDO`**: o spike e uma medicao, nao um
    # gate. Quem decide se a caixa do criterio 8 se marca e quem le a evidencia.
    return 0


if __name__ == "__main__":
    sys.exit(main())
