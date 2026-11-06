"""O receptor de webhook do spike H3 (KAM-100).

Biblioteca padrao e mais nada: o spike corre num portatil de campo atras de um
tunel HTTPS, e uma dependencia nova era uma dependencia a instalar na casa de um
dono de numero. O GWY real e o KAM-013 — **nao e isto**, e isto nunca e
integrado nos servicos.

Duas rotas, as duas de `E1` §5 (CONFIRMADO):

    GET   verificacao: `hub.mode`, `hub.verify_token`, `hub.challenge` ->
          200 com o challenge em texto; qualquer outra coisa -> 403.
    POST  `X-Hub-Signature-256` sobre o corpo **bruto** -> 200; invalida -> 401.

## A ordem das tres operacoes e o produto

    1. ler os bytes do transporte, exactamente como chegaram
    2. verificar a assinatura sobre esses bytes
    3. so entao descodificar o JSON

Trocar 2 e 3 gasta o descodificador em bytes de qualquer pessoa, e o
descodificador e a superficie de ataque maior do que ha aqui. A ordem e um ensaio
(`tests/test_assinatura.py::test_corpo_invalido_mas_assinado_valida`), e nao uma
nota: um corpo correctamente assinado que nao seja JSON valido **tem** de passar
o passo 2 e falhar no 3.

## Responde 200 depois de gravar, e isso e deliberado

`E1` §5 diz «responder 200 de imediato, enfileirar, processar de forma
assincrona». Aqui nao: grava-se primeiro e responde-se depois. A razao e que num
spike de tres numeros o que custa e **perder** um evento — a Meta re-entrega
durante 7 dias com recuo exponencial, pelo que um 500 nosso e recuperavel, e um
200 sobre um evento que nao se gravou nao e. O servico real inverte isto, e o
`docs/tecnica/01` §5.2 e que o descreve.

## O que nao esta aqui

Nao ha subscricao de campos: isso faz-se uma vez no App Dashboard, e a folha do
operador (`protocolo_operador.md`, passo 3) lista os cinco. Nao ha HTTPS: o
tunel e do operador, e `E1` §5 exige certificado valido — um auto-assinado nao
serve e um `http.server` nu nao tem nenhum.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from assinatura import CABECALHO, AssinaturaInvalida, segredo, verificar
from extrair import extrair
from registo import ConteudoRecusado, escrever, validar

#: A variavel de ambiente com o `hub.verify_token`. Como o App Secret, nao vive
#: no repositorio: um token de verificacao em texto claro deixa qualquer pessoa
#: registar-se como o nosso endpoint na app de outra pessoa.
#:
#: **Nao se chama `VARIAVEL_DO_TOKEN`, e nao e estilo.** Com esse nome, a linha
#: fica `<nome com «token»> = "<21 caracteres de entropia alta>"`, que e
#: exactamente o padrao `atribuicao` do gate 9 — e ele ficou vermelho aqui, nesta
#: linha, na primeira medicao. O valor nao e segredo nenhum: e o **nome** da
#: variavel. Preferiu-se mudar o nome da constante a declarar uma area em
#: `ci/secrets-allow.yaml`, porque alargar o gate para um ficheiro descartavel
#: deixa a area aberta depois de a pasta desaparecer.
VARIAVEL_DE_VERIFICACAO = "KAMBA_H3_VERIFY_TOKEN"

#: Quantos bytes se aceitam num corpo. `E1` §5 nao da um limite; este e para o
#: processo nao morrer a ler um pedido que nao e da Meta. 4 MiB chega a qualquer
#: pedaco de `history` que se tenha visto.
LIMITE_DO_CORPO = 4 * 1024 * 1024


def agora() -> str:
    """O instante em UTC, na forma que `registo.PERMITIDOS` admite."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ler_rotulos(caminho: Path) -> dict[str, str]:
    """O mapa `phone_number_id` -> `N1`/`N2`/`N3`, de **fora** do repositorio.

    E um JSON que o operador escreve no portatil dele. Nao entra no repositorio
    e nao tem telefones: o `phone_number_id` e um identificador de canal que a
    Meta atribui, e o rotulo e o que o ficheiro de evidencia mostra.

    Sem o mapa o receptor arranca: as linhas saem sem `numero`, o que faz a
    tabela N1-N3 recusar — e recusar com o ficheiro gravado e melhor do que nao
    gravar.
    """
    if not caminho.is_file():
        return {}
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(dados, dict):
        raise ValueError(f"{caminho}: esperava um objecto JSON de id -> rotulo")
    return {str(k): str(v) for k, v in dados.items()}


def ler_nossos(caminho: Path) -> list[str]:
    """Os `wamid` que enviamos pela API, um por linha. Fora do repositorio.

    Alimenta o `enviada_por_nos` dos ecos, que e a medicao do item NAO
    VERIFICADO de `docs/tecnica/01` §10.3. Um `wamid` em claro leva o numero do
    interlocutor em base64, pelo que este ficheiro **nao entra no repositorio** e
    apaga-se com os registos, no prazo do criterio de privacidade.
    """
    if not caminho.is_file():
        return []
    return [l.strip() for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]


class Receptor(BaseHTTPRequestHandler):
    """O manipulador. A configuracao chega por atributos de classe."""

    destino: Path
    rotulos: dict[str, str]
    nossos: list[str]
    chave: bytes
    token: str

    # `BaseHTTPRequestHandler` imprime cada pedido em `stderr` com o caminho e a
    # linha de pedido inteira. Num spike com numeros reais isso punha um
    # `?hub.verify_token=...` no terminal e no registo da sessao. Silencia-se, e
    # o que se quer saber escreve-se com `anotar`.
    def log_message(self, formato: str, *args: object) -> None:  # noqa: A003
        return

    def anotar(self, texto: str) -> None:
        print(f"[{agora()}] {texto}", flush=True)

    def responder(self, codigo: int, corpo: bytes = b"", tipo: str = "text/plain") -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        if corpo:
            self.wfile.write(corpo)

    def do_GET(self) -> None:  # noqa: N802
        """A verificacao do endpoint (`E1` §5, CONFIRMADO)."""
        consulta = parse_qs(urlparse(self.path).query)
        modo = (consulta.get("hub.mode") or [""])[0]
        token = (consulta.get("hub.verify_token") or [""])[0]
        desafio = (consulta.get("hub.challenge") or [""])[0]
        # `hmac.compare_digest` tambem aqui: o token e um segredo curto, e uma
        # comparacao que saia no primeiro byte diferente diz quantos acertaram.
        import hmac

        if modo == "subscribe" and desafio and hmac.compare_digest(token, self.token):
            self.anotar("GET verificacao: token valido, devolvo o challenge")
            self.responder(200, desafio.encode("utf-8"))
            return
        # A mensagem **nao** diz qual das tres condicoes falhou: dizer «token
        # errado» confirma a quem sondar que o modo e o challenge estavam bem.
        self.anotar("GET verificacao: recusado")
        self.responder(403, b"recusado")

    def do_POST(self) -> None:  # noqa: N802
        """Um lote de eventos. Assinatura primeiro, descodificacao depois."""
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.responder(400, b"Content-Length invalido")
            return
        if tamanho <= 0 or tamanho > LIMITE_DO_CORPO:
            self.responder(413, b"corpo ausente ou grande demais")
            return

        # **Os bytes, exactamente como chegaram.** Nao se descodificam, nao se
        # normalizam e nao se voltam a serializar em sitio nenhum deste metodo.
        bruto = self.rfile.read(tamanho)
        if len(bruto) != tamanho:
            self.responder(400, b"corpo truncado")
            return

        try:
            verificar(bruto, self.headers.get(CABECALHO), self.chave)
        except AssinaturaInvalida as e:
            self.anotar(f"POST recusado: {e}")
            self.responder(401, b"assinatura invalida")
            return

        try:
            corpo = json.loads(bruto)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # Assinado e ilegivel: vale a pena saber, porque quem o assinou tem o
            # App Secret. A mensagem **nao** leva o corpo.
            self.anotar(f"POST assinado mas ilegivel ({e.__class__.__name__})")
            self.responder(400, b"corpo nao e JSON valido")
            return
        if not isinstance(corpo, dict):
            self.responder(400, b"corpo nao e um objecto")
            return

        instante = agora()
        # **Tudo ou nada, e isto e uma correccao.** A primeira versao escrevia
        # dentro do laco: um `ConteudoRecusado` a meio — um valor que nao casa a
        # forma, num corpo correctamente assinado — deixava as linhas anteriores
        # gravadas, perdia as seguintes e **nao respondia nada**, porque o
        # `except` so apanhava `AssinaturaInvalida`. A Meta re-entrega «ate 7
        # dias com recuo exponencial» (`E1` §5), pelo que cada tentativa voltava
        # a acrescentar as primeiras linhas e falhava no mesmo sitio: o ficheiro
        # acumulava duplicados do mesmo evento, e o `tabela._historico` soma-os
        # em bruto — a inflar a contagem de que depende o limiar «≥ 95% por
        # contagem» do criterio 3. Apanhado pela revisao adversarial, com a
        # reentrega medida.
        #
        # Valida-se o lote inteiro antes de escrever uma linha. Um lote recusado
        # grava zero, e a reentrega volta a recusar zero.
        try:
            linhas = extrair(corpo, self.rotulos, self.nossos, instante)
            for linha in linhas:
                validar(linha)
        except ConteudoRecusado as e:
            self.anotar(f"POST assinado mas recusado pelo registo: {e}")
            self.responder(422, b"corpo assinado com valor fora da forma")
            return
        for linha in linhas:
            escrever(self.destino, linha)
        self.anotar(f"POST aceite: {len(linhas)} linha(s) gravada(s)")
        self.responder(200, b"ok")

    def handle_one_request(self) -> None:
        """Responde **sempre**, mesmo a um erro que nao previmos.

        O `BaseHTTPRequestHandler` deixa a ligacao cair quando o manipulador
        levanta, e um pedido sem resposta e indistinguivel de um receptor em
        baixo: a Meta re-entrega e ninguem sabe porque. Um 500 e informacao; o
        silencio nao e. A mensagem **nao leva** o corpo nem a excepcao — vai para
        o registo local, onde o operador a ve.
        """
        try:
            super().handle_one_request()
        except Exception as e:  # noqa: BLE001
            self.anotar(f"ERRO nao previsto ({e.__class__.__name__}); respondo 500")
            try:
                self.responder(500, b"erro interno")
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="receptor",
        description="Receptor de webhook do spike H3 (KAM-100). Descartavel.",
    )
    p.add_argument("--porta", type=int, default=8787)
    p.add_argument("--destino", default="eventos.jsonl", help="o JSON-lines a escrever")
    p.add_argument("--rotulos", default="rotulos.json", help="phone_number_id -> N1/N2/N3")
    p.add_argument("--nossos", default="nossos.txt", help="os wamid enviados pela API")
    a = p.parse_args(argv)

    token = os.environ.get(VARIAVEL_DE_VERIFICACAO, "")
    if not token:
        print(
            f"ERRO: {VARIAVEL_DE_VERIFICACAO} nao esta definida. O token de verificacao "
            "vive no cofre; o repositorio e publico.",
            file=sys.stderr,
        )
        return 2
    try:
        chave = segredo()
    except RuntimeError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 2

    Receptor.destino = Path(a.destino)
    Receptor.rotulos = ler_rotulos(Path(a.rotulos))
    Receptor.nossos = ler_nossos(Path(a.nossos))
    Receptor.chave = chave
    Receptor.token = token

    if not Receptor.rotulos:
        print(
            f"AVISO: {a.rotulos} nao existe ou esta vazio. As linhas saem sem "
            "`numero` e a tabela N1-N3 vai recusar.",
            file=sys.stderr,
        )

    servidor = ThreadingHTTPServer(("127.0.0.1", a.porta), Receptor)
    print(
        f"receptor H3 em http://127.0.0.1:{a.porta} -> {a.destino} "
        f"({len(Receptor.rotulos)} rotulo(s), {len(Receptor.nossos)} wamid(s) nossos)"
    )
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nterminado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
