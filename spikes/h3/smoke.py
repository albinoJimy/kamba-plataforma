"""Ida e volta real contra o receptor: assinatura valida, invalida e corpo bruto.

Os ensaios de `tests/` exercitam as funcoes. Este alvo exercita o **processo**:
levanta o receptor numa porta, faz pedidos HTTP a serio e le o ficheiro que ele
escreveu. E a diferenca entre «a funcao verifica» e «o receptor recusa», e e a
unica forma de ver que a ordem das operacoes dentro do `do_POST` esta certa.

Corre-se sem argumentos e nao precisa de rede nem de segredos do cofre: inventa
um segredo de ensaio para o processo filho.

    PYTHONPATH='spikes/h3;libs/py-core/src' python spikes/h3/smoke.py

Sai 0 se todos os casos passarem, 1 se algum falhar, e **conta-os em vez de os
citar** — a primeira versao imprimia «6 de 6» com o numero a mao e corria sete.
Nao e um portao — ver o README: `spikes/` nao entra em portao nenhum.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

from assinatura import CABECALHO, calcular  # noqa: E402

SEGREDO = "segredo-de-smoke-do-spike-h3"
VERIFICACAO = "verificacao-de-smoke"
PORTA = 8799

#: O canal e o rotulo, como o `rotulos.json` do operador os teria.
CANAL = "900900900900900"

#: Um corpo de `account_update` com o evento final do ES v4 de coexistencia.
CORPO = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "1" * 15,
            "changes": [
                {
                    "field": "account_update",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": CANAL},
                        "event": "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
                    },
                }
            ],
        }
    ],
}


def pedir(caminho: str, dados: bytes | None = None, cabecalhos: dict | None = None):
    """`(codigo, corpo)` de um pedido ao receptor. Um 4xx nao levanta."""
    pedido = urllib.request.Request(
        f"http://127.0.0.1:{PORTA}{caminho}", data=dados, headers=cabecalhos or {}
    )
    try:
        with urllib.request.urlopen(pedido, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def esperar_pronto(processo: subprocess.Popen, limite: float = 15.0) -> None:
    """Espera que a porta responda. Nao e um `sleep` fixo: sonda."""
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if processo.poll() is not None:
            raise RuntimeError(
                f"o receptor morreu com {processo.returncode}: "
                f"{(processo.stderr.read() if processo.stderr else b'')!r}"
            )
        try:
            pedir("/?hub.mode=x")
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("o receptor nao respondeu dentro do limite")


def main() -> int:
    with tempfile.TemporaryDirectory() as pasta:
        destino = Path(pasta) / "eventos.jsonl"
        rotulos = Path(pasta) / "rotulos.json"
        rotulos.write_text(json.dumps({CANAL: "N1"}), encoding="utf-8")

        ambiente = dict(os.environ)
        ambiente["KAMBA_H3_APP_SECRET"] = SEGREDO
        ambiente["KAMBA_H3_VERIFY_TOKEN"] = VERIFICACAO
        ambiente["PYTHONPATH"] = os.pathsep.join(
            [str(AQUI), *filter(None, [ambiente.get("PYTHONPATH", "")])]
        )

        processo = subprocess.Popen(
            [
                sys.executable,
                str(AQUI / "receptor.py"),
                "--porta", str(PORTA),
                "--destino", str(destino),
                "--rotulos", str(rotulos),
            ],
            env=ambiente,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        falhas: list[str] = []
        # **A contagem conta-se, nao se escreve.** A primeira versao imprimia
        # «6 de 6 casos» com o numero a mao, e corria sete verificacoes: a saida
        # verde do unico ensaio de ida e volta reportava menos casos do que
        # executou. Apanhado pela revisao adversarial.
        corridos = 0
        try:
            esperar_pronto(processo)

            def verificar(nome: str, condicao: bool, detalhe: str = "") -> None:
                nonlocal corridos
                corridos += 1
                print(f"  {'ok  ' if condicao else 'FALHA'}  {nome}{detalhe}")
                if not condicao:
                    falhas.append(nome)

            # 1. O GET de verificacao com o token certo devolve o challenge.
            codigo, corpo = pedir(
                f"/?hub.mode=subscribe&hub.verify_token={VERIFICACAO}&hub.challenge=12345"
            )
            verificar(
                "GET com o token certo devolve 200 e o challenge",
                codigo == 200 and corpo == b"12345",
                f" ({codigo}, {corpo!r})",
            )

            # 2. O GET com o token errado da 403, e nao o challenge.
            codigo, corpo = pedir(
                "/?hub.mode=subscribe&hub.verify_token=errado&hub.challenge=12345"
            )
            verificar(
                "GET com o token errado da 403 e nao o challenge",
                codigo == 403 and b"12345" not in corpo,
                f" ({codigo})",
            )

            # 3. Um POST assinado passa e grava.
            bruto = json.dumps(CORPO, separators=(",", ":")).encode("utf-8")
            codigo, _ = pedir(
                "/", bruto, {CABECALHO: calcular(bruto, SEGREDO.encode()), "Content-Type": "application/json"}
            )
            verificar("POST assinado da 200", codigo == 200, f" ({codigo})")
            linhas = destino.read_text(encoding="ascii").strip().splitlines() if destino.is_file() else []
            verificar(
                "e gravou uma linha com o rotulo e o evento",
                len(linhas) == 1
                and json.loads(linhas[0])["numero"] == "N1"
                and json.loads(linhas[0])["evento"]
                == "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
                f" ({len(linhas)} linha(s))",
            )

            # 4. Um POST com assinatura de outro corpo e recusado.
            codigo, _ = pedir(
                "/",
                bruto,
                {CABECALHO: calcular(b'{"outro":1}', SEGREDO.encode())},
            )
            verificar("POST com assinatura de outro corpo da 401", codigo == 401, f" ({codigo})")

            # 5. **O corpo bruto.** A mesma arvore com bytes diferentes, com a
            # assinatura do original: tem de ser recusada. Numa implementacao
            # que re-serializasse, isto dava 200 — e e o fail-open silencioso.
            variante = json.dumps(CORPO, indent=1).encode("utf-8")
            codigo, _ = pedir(
                "/", variante, {CABECALHO: calcular(bruto, SEGREDO.encode())}
            )
            verificar(
                "POST com a MESMA arvore e bytes diferentes da 401",
                codigo == 401,
                f" ({codigo})",
            )

            # 6. **Um cabecalho nao-ASCII responde 401, e nao fecha a ligacao.**
            # O `http.server` descodifica os cabecalhos em latin-1, e o
            # `compare_digest` levanta `TypeError` sobre um `str` nao-ASCII — que
            # nao e `AssinaturaInvalida`. O receptor fechava a ligacao sem
            # responder, em vez do 4xx que `E1` §5 pede.
            try:
                codigo, _ = pedir(
                    "/", bruto, {CABECALHO: "sha256=" + "á" * 64}
                )
            except OSError as e:
                codigo = f"<ligacao fechada: {e.__class__.__name__}>"
            verificar(
                "cabecalho nao-ASCII da 401 e nao fecha a ligacao",
                codigo == 401,
                f" ({codigo})",
            )

            # 7. **Um corpo assinado com um valor fora da forma grava zero.**
            # Antes, o `ConteudoRecusado` saltava do laco com as linhas
            # anteriores ja gravadas e sem resposta, e cada reentrega da Meta
            # voltava a acrescenta-las.
            mau = json.dumps(
                {
                    "object": "whatsapp_business_account",
                    "entry": [
                        {
                            "id": "1" * 15,
                            "changes": [
                                {
                                    "field": "account_update",
                                    "value": {
                                        "metadata": {"phone_number_id": CANAL},
                                        "event": "minusculas fora da forma",
                                    },
                                }
                            ],
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode("utf-8")
            antes = destino.read_text(encoding="ascii")
            try:
                codigo, _ = pedir("/", mau, {CABECALHO: calcular(mau, SEGREDO.encode())})
            except OSError as e:
                codigo = f"<ligacao fechada: {e.__class__.__name__}>"
            verificar(
                "valor fora da forma responde 422 e nao fecha a ligacao",
                codigo == 422,
                f" ({codigo})",
            )
            verificar(
                "e gravou zero linhas (nao ha escrita parcial)",
                destino.read_text(encoding="ascii") == antes,
            )

            # 8. Nenhuma das recusas gravou nada: continua a haver uma linha so.
            linhas = destino.read_text(encoding="ascii").strip().splitlines()
            verificar(
                "nenhuma recusa gravou: continua 1 linha",
                len(linhas) == 1,
                f" ({len(linhas)})",
            )
        finally:
            processo.terminate()
            try:
                processo.wait(timeout=5)
            except subprocess.TimeoutExpired:
                processo.kill()

    if falhas:
        print(f"\nsmoke H3: {len(falhas)} de {corridos} FALHARAM: {falhas}")
        return 1
    print(f"\nsmoke H3: {corridos} de {corridos} casos passaram")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
