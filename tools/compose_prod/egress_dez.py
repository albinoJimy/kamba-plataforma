"""O guiao dos dez destinos: *egress default-deny* medido (KAM-076, criterio 3).

O criterio 3 pede um guiao com **dez destinos** e tres afirmacoes:

1. de um contentor em `data`, **qualquer** ligacao externa falha;
2. de `app`, so passam `graph.facebook.com`, o FQDN do facilitador e os FQDN de
   LLM/STT autorizados;
3. as restantes sao **bloqueadas e registadas**.

A terceira e metade do criterio e e a que se esquece. Aqui le-se o
`access_log` do proxy e exige-se uma linha com `veredicto: 403` para **cada**
destino recusado: um bloqueio que nao deixa rasto nao e observavel, e um
bloqueio que ninguem ve e um incidente que ninguem investiga.

## O que este guiao mede, e o que deliberadamente nao mede

Mede o **veredicto do proxy**, nao se o destino responde. Um destino permitido
tem de receber algo que **nao** seja 403 — um `200 Connection established`
quando a rede do *runner* chega la, ou um 503/504 quando nao chega. Um destino
recusado tem de receber exactamente **403**, com a mensagem da allowlist.

A distincao nao e conveniencia: e o que torna o guiao uma prova sobre a
**politica** e nao sobre a ligacao de quem o corre. Um guiao que exigisse 200
dava vermelho em qualquer *runner* sem saida para a Internet — e seria desligado
pela primeira pessoa que o encontrasse vermelho sem ter nada quebrado. A
acessibilidade real fica registada no relatorio, como medicao, ao lado do
veredicto.

## Porque corre contra o compose de **producao**, e nao contra uma replica

Levanta-se `proxy-saida` do proprio `docker-compose.prod.yml`, com as quatro
redes de verdade, e as sondas entram por `docker run --network`. Uma replica de
ensaio provaria que *uma* configuracao parecida nega por omissao; isto prova que
**a que vai para producao** nega. As sondas nao sao servicos de nenhum compose,
de proposito: um servico de ensaio num compose do repositorio pediria lista de
saidas propria e apareceria no conjunto reduzido.

As variaveis que o compose exige com `:?` recebem valores de **marcador** para
esta execucao: o guiao levanta um so servico, e nenhum segredo verdadeiro entra.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from kamba_yaml import YamlSubsetError, load_file

from .lint import ALLOWLIST, PROD, ConfiguracaoInvalida

#: A sonda corre na imagem oficial do Python, que o inventario ja fixa. Nao
#: traz digest novo: e a mesma constante que `db/tests_*` usam para o Node.
#: Declarada em `fontes_adicionais` de `ci/supply-chain/imagens.yaml`.
IMAGEM_SONDA = (
    "python:3.12-slim-trixie"
    "@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1"
)

#: O nome do projecto do compose: e dele que vem o nome das redes.
PROJECTO = "kamba-prod"

#: Quantos segundos se espera pelas linhas de `access_log` do proxy. O Envoy
#: escreve stdout com *buffer* (medido): a leitura imediata via uma linha das
#: dez, e as dez apareciam segundos depois.
ESPERA_PELO_REGISTO = 20

#: Os dez destinos do criterio 3. Quatro permitidos (os que tem dono declarado)
#: e seis recusados, e cada recusa tem a razao escrita.
#:
#: `permitido` e o que o **proxy** tem de decidir, e nao se o destino responde.
DESTINOS: tuple[dict, ...] = (
    {
        "fqdn": "graph.facebook.com",
        "permitido": True,
        "razao": "Graph API da Meta; declarado por `gwy` (ADR-001, doc 09 §3.2 regra 2).",
    },
    {
        "fqdn": "api.anthropic.com",
        "permitido": True,
        "razao": "Fornecedor de `kamba-router`, `kamba-chat` e `screening-nano`; declarado por `litellm`.",
    },
    {
        "fqdn": "api.openai.com",
        "permitido": True,
        "razao": "*Fallback* de `kamba-chat`; declarado por `litellm`.",
    },
    {
        "fqdn": "generativelanguage.googleapis.com",
        "permitido": True,
        "razao": "Fornecedor de `kamba-vision` e `kamba-embed`; declarado por `litellm`.",
    },
    {
        "fqdn": "api.proxypay.co.ao",
        "permitido": False,
        "razao": (
            "O FQDN do facilitador, que o criterio 3 nomeia como **permitido** — e que "
            "aqui esta recusado de proposito. Nenhum servico do repositorio o declara: "
            "nao ha `services/pay/`, e o adaptador de pagamento e o KAM-056. Um destino "
            "na allowlist sem dono e o contrario de negar por omissao, e seria ainda "
            "transferencia sem `apd_ref` (KAM-069). O criterio 3 fica **parcialmente "
            "satisfeito**, e esta dito no PR em vez de ser dado por cumprido."
        ),
    },
    {
        "fqdn": "raw.githubusercontent.com",
        "permitido": False,
        "razao": (
            "Medido no KAM-030: o LiteLLM sai para aqui no arranque, para buscar o mapa "
            "de precos. Fecha-se desligando a saida (`LITELLM_LOCAL_MODEL_COST_MAP`), "
            "nao declarando o destino."
        ),
    },
    {
        "fqdn": "beacon.langchain.com",
        "permitido": False,
        "razao": (
            "O *beacon* do LangGraph Server (ADR-002). A biblioteca MIT nao o chama; "
            "este destino existe na lista para que, se algum dia alguem trouxer o "
            "Server, a rede o recuse antes de a licenca o apanhar."
        ),
    },
    {
        "fqdn": "pypi.org",
        "permitido": False,
        "razao": (
            "Instalacao em runtime (`docs/tecnica/08` §4.8). O incidente-referencia e o "
            "LiteLLM 1.82.7/1.82.8 maliciosas no PyPI; um contentor de producao que "
            "chegue ao PyPI pode trazer codigo que ninguem reviu."
        ),
    },
    {
        "fqdn": "registry.npmjs.org",
        "permitido": False,
        "razao": "O mesmo que o PyPI, do lado do Node.",
    },
    {
        "fqdn": "example.com",
        "permitido": False,
        "razao": (
            "O destino de controlo: um FQDN sem nenhuma relacao com a plataforma. Se "
            "**este** passasse, a allowlist nao estava a ser aplicada."
        ),
    },
)

#: A sonda de `app`: fala CONNECT ao proxy e devolve o veredicto de cada
#: destino. Socket cru de proposito — o que se quer e a linha de estado que o
#: proxy devolve, sem uma biblioteca a interpreta-la ou a repetir o pedido.
_SONDA_APP = r"""
import json, socket, sys
destinos = json.loads(sys.argv[1])
proxy_host, proxy_porta = sys.argv[2], int(sys.argv[3])
saida = {}
for fqdn in destinos:
    try:
        with socket.create_connection((proxy_host, proxy_porta), timeout=15) as s:
            pedido = (
                "CONNECT %s:443 HTTP/1.1\r\nHost: %s:443\r\n"
                "Proxy-Connection: close\r\n\r\n" % (fqdn, fqdn)
            )
            s.sendall(pedido.encode())
            dados = b""
            while b"\r\n" not in dados and len(dados) < 4096:
                pedaco = s.recv(1024)
                if not pedaco:
                    break
                dados += pedaco
            linha = dados.split(b"\r\n", 1)[0].decode("latin-1")
            partes = linha.split(" ")
            saida[fqdn] = {
                "estado": int(partes[1]) if len(partes) > 1 and partes[1].isdigit() else None,
                "linha": linha,
            }
    except Exception as erro:
        saida[fqdn] = {"estado": None, "linha": "erro: %s" % erro}
print(json.dumps(saida))
"""

#: A sonda de `data`: tenta ligar **directamente**, sem proxy. Nenhuma pode
#: passar — e a primeira afirmacao do criterio 3. Mede tambem a resolucao de
#: nomes, porque numa rede `internal: true` nem o DNS responde.
_SONDA_DATA = r"""
import json, socket, sys
destinos = json.loads(sys.argv[1])
saida = {}
for fqdn in destinos:
    registo = {"dns": None, "tcp": None}
    try:
        registo["dns"] = socket.gethostbyname(fqdn)
    except Exception as erro:
        registo["dns"] = "erro: %s" % type(erro).__name__
    try:
        with socket.create_connection((fqdn, 443), timeout=8):
            registo["tcp"] = "ABERTO"
    except Exception as erro:
        registo["tcp"] = "erro: %s" % type(erro).__name__
    saida[fqdn] = registo
print(json.dumps(saida))
"""

#: Valores de marcador para as variaveis que o compose exige com `:?`. O guiao
#: levanta **so** o `proxy-saida`; nenhum segredo verdadeiro entra aqui, e e por
#: isso que sao visiveis e nao vem do cofre.
MARCADORES = {
    "KAMBA_COMMIT_SHA": "ensaio-egress-dez",
    "KAMBA_DATA_CLASS": "synthetic",
    "POSTGRES_USER": "marcador",
    "POSTGRES_PASSWORD": "marcador",
    "CHATWOOT_DB_USER": "marcador",
    "CHATWOOT_DB_PASSWORD": "marcador",
    "CHATWOOT_SECRET_KEY_BASE": "marcador",
    "CHATWOOT_FRONTEND_URL": "https://marcador.invalid",
    # Os nomes que o `llm/litellm.config.yaml` **gerado** le. Nao sao os do
    # `docker-compose.llm.yml` — ver a nota no compose de producao.
    "KAMBA_SECRET_LITELLM_MASTER_KEY": "sk-marcador",
    "KAMBA_SECRET_LLM_PROVIDER_KEY__anthropic": "marcador",
    "KAMBA_SECRET_LLM_PROVIDER_KEY__openai": "marcador",
    "KAMBA_SECRET_LLM_PROVIDER_KEY__google": "marcador",
    # KAM-178: o COM passou a exigir dois segredos e a cadeia de ligacao ao
    # arranque, e o AGR passou a exigir a credencial do COM. As quatro entram
    # aqui pela razao escrita acima — o guiao levanta **so** o `proxy-saida`,
    # nenhum destes servicos arranca, e por isso nenhum segredo verdadeiro
    # precisa de existir. Sem elas o `docker compose up proxy-saida` falha na
    # **interpolacao**, antes de haver contentor nenhum (medido: gate 6 vermelho
    # no PR #125, `required variable KAMBA_SECRET_COM_INTERNAL_TOKEN is missing a
    # value`).
    "KAMBA_SECRET_COM_INTERNAL_TOKEN": "marcador",
    "KAMBA_SECRET_SEGREDO_INTENTS": "marcador",
    "KAMBA_COM_DB_URL": "postgresql://marcador@marcador.invalid:5432/marcador",
    # KAM-187: os quatro processos do `worker-canal` exigem as suas ligacoes, as
    # chaves de identidade, a credencial do AGR e a subscricao. Mesma razao das
    # de cima, e o mesmo sintoma sem elas: gate 6 vermelho na interpolacao
    # (`required variable KAMBA_SECRET_AGR_INTERNAL_TOKEN is missing a value`).
    # O `test_cada_variavel_obrigatoria_tem_marcador` prende a lista ao compose.
    "KAMBA_ENTRADA_DB_URL": "postgresql://marcador@marcador.invalid:5432/marcador",
    "KAMBA_CHR_RESOLVER_DB_URL": "postgresql://marcador@marcador.invalid:5432/marcador",
    "KAMBA_CHR_IDENTITY_DB_URL": "postgresql://marcador@marcador.invalid:5432/marcador",
    "KAMBA_PUBLICADOR_DB_URL": "postgresql://marcador@marcador.invalid:5432/marcador",
    "KAMBA_CONSUMIDOR_DB_URL": "postgresql://marcador@marcador.invalid:5432/marcador",
    "KAMBA_CONSUMIDOR_OPS_DB_URL": "postgresql://marcador@marcador.invalid:5432/marcador",
    "KAMBA_SECRET_PEPPER_CONTACT_HMAC": "marcador",
    "KAMBA_SECRET_KEK_CONTACT_DEK": "marcador",
    "KAMBA_SECRET_AGR_INTERNAL_TOKEN": "marcador",
    "KAMBA_CONSUMER": "marcador",
    # KAM-194: o `idx` exige a credencial dele e as duas senhas da base, e a
    # ponte do IDX apresenta a mesma credencial. Mesma razao e mesmo sintoma.
    "KAMBA_SECRET_IDX_INTERNAL_TOKEN": "marcador",
    "KAMBA_DB_NAME": "marcador",
    "KAMBA_SECRET_DB_APP_PASSWORD": "marcador",
    "KAMBA_SECRET_DB_BATCH_PASSWORD": "marcador",
}


def _ambiente() -> dict[str, str]:
    ambiente = dict(os.environ)
    for nome, valor in MARCADORES.items():
        ambiente.setdefault(nome, valor)
    return ambiente


def _compose(raiz: Path, *argumentos: str, verificar: bool = True) -> subprocess.CompletedProcess:
    comando = [
        "docker", "compose",
        "-f", str(raiz / PROD),
        "-p", PROJECTO,
        *argumentos,
    ]
    return subprocess.run(
        comando, capture_output=True, text=True, check=verificar, env=_ambiente()
    )


def _sonda(rede: str, guiao: str, destinos: list[str]) -> dict:
    """Corre uma sonda numa rede e devolve o que ela imprimiu."""
    resultado = subprocess.run(
        [
            "docker", "run", "--rm",
            "--network", f"{PROJECTO}_{rede}",
            IMAGEM_SONDA,
            "python", "-c", guiao, json.dumps(destinos), "proxy-saida", "3128",
        ],
        capture_output=True, text=True, check=False,
    )
    if resultado.returncode != 0:
        raise ConfiguracaoInvalida(
            f"a sonda em `{rede}` saiu com {resultado.returncode}: "
            f"{resultado.stderr.strip()[:400]}"
        )
    try:
        return json.loads(resultado.stdout.strip().split("\n")[-1])
    except json.JSONDecodeError as excepcao:
        raise ConfiguracaoInvalida(
            f"a sonda em `{rede}` nao imprimiu JSON: {resultado.stdout[:400]}"
        ) from excepcao


def _allowlist(raiz: Path) -> set[str]:
    try:
        dados = load_file(raiz / ALLOWLIST)
    except (OSError, YamlSubsetError) as excepcao:
        raise ConfiguracaoInvalida(f"{ALLOWLIST}: ilegivel: {excepcao}") from excepcao
    return {d.get("fqdn") for d in (dados.get("destinos") or []) if d.get("fqdn")}


def _conferir_coerencia(raiz: Path) -> list[str]:
    """O guiao e a allowlist tem de concordar, senao o guiao nao mede nada.

    Um destino marcado `permitido` que nao esteja na allowlist — ou o contrario
    — e um guiao que passaria a afirmar o oposto do que o ficheiro diz. Falha
    antes de levantar contentores.
    """
    allowlist = _allowlist(raiz)
    falhas: list[str] = []
    for destino in DESTINOS:
        na_lista = destino["fqdn"] in allowlist
        if destino["permitido"] and not na_lista:
            falhas.append(
                f"`{destino['fqdn']}` esta marcado permitido no guiao e nao esta em "
                f"{ALLOWLIST}"
            )
        if not destino["permitido"] and na_lista:
            falhas.append(
                f"`{destino['fqdn']}` esta marcado recusado no guiao e **esta** em "
                f"{ALLOWLIST}"
            )
    if len(DESTINOS) != 10:
        falhas.append(f"o criterio 3 pede dez destinos e o guiao tem {len(DESTINOS)}")
    return falhas


def correr(raiz: Path, manter: bool = False) -> int:
    if not (raiz / PROD).is_file():
        raise ConfiguracaoInvalida(f"compose ausente: {PROD}")
    falhas_de_coerencia = _conferir_coerencia(raiz)
    if falhas_de_coerencia:
        for falha in falhas_de_coerencia:
            print(f"compose_prod egress-dez: {falha}", file=sys.stderr)
        return 2

    nomes = [d["fqdn"] for d in DESTINOS]
    falhas: list[str] = []
    print(f"compose_prod egress-dez: a levantar `proxy-saida` de {PROD}")
    try:
        # `create` **sem arrancar** o `postgres`: e so para que a rede `data`
        # exista. O Docker nao cria uma rede que nenhum contentor use (medido),
        # e a primeira afirmacao do criterio 3 e sobre um contentor em `data` —
        # sem a rede, a sonda nao tinha onde correr e o guiao media nove
        # destinos em vez de dez. Arrancar o PostgreSQL a serio levaria meio
        # minuto e um volume, para provar o mesmo.
        _compose(raiz, "create", "--no-build", "postgres")
        _compose(raiz, "up", "-d", "--wait", "proxy-saida")
    except subprocess.CalledProcessError as erro:
        raise ConfiguracaoInvalida(
            f"`docker compose up proxy-saida` falhou: {(erro.stderr or '')[:600]}"
        ) from erro

    try:
        # ---------------------------------------------------- `data` nao sai
        de_data = _sonda("data", _SONDA_DATA, nomes)
        print("\n-- de um contentor em `data` (sem proxy): nenhuma ligacao passa")
        for fqdn in nomes:
            registo = de_data.get(fqdn, {})
            passou = registo.get("tcp") == "ABERTO"
            print(
                f"   {'FALHA ' if passou else 'ok    '} {fqdn:40s} "
                f"dns={registo.get('dns')} tcp={registo.get('tcp')}"
            )
            if passou:
                falhas.append(
                    f"de `data` a ligacao a `{fqdn}` **abriu**. A rede `data` tem de "
                    "ser `internal: true` (doc 09 §3.2 regra 2)."
                )

        # ------------------------- `edge` tem rota, e isso **mede-se** tambem
        #
        # O criterio 3 nomeia **quatro** redes e a primeira versao deste guiao
        # sondava duas. A `edge` tem rota de saida por desenho — e dela que o
        # `proxy-saida` sai e e nela que o `proxy-tls` publica 443 —, pelo que
        # nao se exige que esteja fechada. Mede-se e diz-se, porque o que nao
        # se mede fica a parecer fechado: um contentor em `edge` alcanca a
        # Internet **sem passar pela allowlist e sem deixar linha no
        # `access_log`**. Achado da revisao adversarial.
        #
        # O que **garante** que isso nao se espalha e a regra `servico-em-edge`
        # do lint, que so la deixa estar o `proxy-tls` e o `proxy-saida`.
        de_edge = _sonda("edge", _SONDA_DATA, nomes)
        abertos_em_edge = [f for f in nomes if de_edge.get(f, {}).get("tcp") == "ABERTO"]
        print(
            "\n-- de um contentor em `edge` (sem proxy): tem rota, por desenho — "
            "e e por isso que so dois servicos podem estar la"
        )
        print(
            f"   medido  {len(abertos_em_edge)} de {len(nomes)} destinos abertos "
            f"directamente, sem allowlist e sem registo: {abertos_em_edge or 'nenhum'}"
        )
        print(
            "   nota    quem garante que isto nao se espalha e a regra "
            "`servico-em-edge` do lint (so `proxy-tls` e `proxy-saida`), e nao esta "
            "sonda"
        )

        # -------------------------------------- `app` sai so pela allowlist
        de_app = _sonda("app", _SONDA_APP, nomes)
        print("\n-- de `app`, pelo proxy: so a allowlist passa")
        alcancados = 0
        inalcancaveis: list[str] = []
        for destino in DESTINOS:
            fqdn = destino["fqdn"]
            registo = de_app.get(fqdn, {})
            estado = registo.get("estado")
            recusado = estado == 403
            if destino["permitido"] and recusado:
                falhas.append(
                    f"`{fqdn}` esta na allowlist e o proxy respondeu 403. "
                    f"{destino['razao']}"
                )
            if not destino["permitido"] and not recusado:
                falhas.append(
                    f"`{fqdn}` **nao** esta na allowlist e o proxy respondeu "
                    f"{estado} em vez de 403. {destino['razao']}"
                )
            # **200 nao e o mesmo que «nao-403», e a diferenca importa.** Um 503
            # (`dns_resolution_failure`, `connection_timeout`) tambem nao e 403,
            # e com a regra antiga contava como «permitido» — pelo que o guiao
            # dava verde sobre um destino que o proxy **nao alcanca**. Foi a
            # revisao adversarial a medi-lo: `graph.facebook.com` a 503 por
            # cache de DNS fria, com o relatorio a dizer «4 permitidos, todos
            # com o veredicto esperado».
            if destino["permitido"]:
                if estado == 200:
                    alcancados += 1
                elif not recusado:
                    inalcancaveis.append(f"{fqdn} ({estado})")
            esperado = "200" if destino["permitido"] else "403"
            if destino["permitido"]:
                marca = "ok    " if estado == 200 else ("FALHA " if recusado else "INALC.")
            else:
                marca = "ok    " if recusado else "FALHA "
            print(
                f"   {marca} {fqdn:40s} "
                f"esperado={esperado:5s} obtido={estado} ({registo.get('linha', '')[:40]})"
            )

        permitidos_total = sum(1 for d in DESTINOS if d["permitido"])
        if inalcancaveis:
            print(
                f"\n   AVISO: {len(inalcancaveis)} destino(s) da allowlist nao foram "
                f"alcancados (nao e 403, mas tambem nao e 200): {inalcancaveis}.\n"
                "   O proxy deixou passar e a ligacao nao chegou. Em producao isto e "
                "uma mensagem perdida."
            )
        # O controlo que torna a metade positiva significativa: se **nenhum**
        # destino da allowlist foi alcancado, nao se distingue «a allowlist
        # permite» de «esta maquina nao tem saida». Nesse caso o guiao diz
        # `inconclusivo` em vez de verde — a mesma regra que o KAM-078 aplica
        # as falhas da Meta no *smoke*.
        if permitidos_total and alcancados == 0:
            falhas.append(
                "INCONCLUSIVO na metade positiva: nenhum dos "
                f"{permitidos_total} destinos da allowlist devolveu 200. Nao se "
                "distingue «a allowlist permite» de «esta maquina nao tem saida», e "
                "um verde aqui afirmaria o que nao se mediu."
            )

        # ------------------------------- e as recusas ficaram **registadas**
        #
        # Espera-se pelas linhas em vez de as ler uma vez, e a razao foi medida:
        # o Envoy escreve o `access_log` para stdout com *buffer*, e numa
        # primeira versao deste guiao a leitura imediata via **uma** linha das
        # dez. As dez estavam la segundos depois. Ler uma vez dava um gate que
        # falha ao acaso — e um gate que falha ao acaso e desligado por quem o
        # encontra vermelho sem ter nada quebrado.
        esperadas = sum(1 for d in DESTINOS if not d["permitido"])
        linhas_json: list[dict] = []
        for tentativa in range(ESPERA_PELO_REGISTO):
            registos = _compose(raiz, "logs", "--no-log-prefix", "proxy-saida", verificar=False)
            linhas_json = []
            for linha in (registos.stdout or "").splitlines():
                linha = linha.strip()
                if not linha.startswith("{"):
                    continue
                try:
                    linhas_json.append(json.loads(linha))
                except json.JSONDecodeError:
                    continue
            recusas = sum(1 for e in linhas_json if str(e.get("veredicto")) == "403")
            if recusas >= esperadas:
                break
            if tentativa + 1 < ESPERA_PELO_REGISTO:
                time.sleep(1)
        print(
            f"\n-- o registo do proxy: {len(linhas_json)} linha(s) JSON de `access_log`"
        )
        if not linhas_json:
            falhas.append(
                "o proxy nao deixou nenhuma linha de `access_log` em JSON. A segunda "
                "metade do criterio 3 e «bloqueadas **e registadas**»: um bloqueio sem "
                "rasto nao e observavel."
            )
        for destino in DESTINOS:
            if destino["permitido"]:
                continue
            fqdn = destino["fqdn"]
            registada = any(
                str(entrada.get("veredicto")) == "403"
                and re.match(rf"^{re.escape(fqdn)}(?::\d+)?$", str(entrada.get("autoridade", "")))
                for entrada in linhas_json
            )
            print(f"   {'ok    ' if registada else 'FALHA '} 403 registado para {fqdn}")
            if not registada:
                falhas.append(
                    f"a recusa de `{fqdn}` nao aparece no `access_log` com "
                    "`veredicto: 403`. Bloquear sem registar e metade do criterio 3."
                )
    finally:
        if manter:
            print(
                f"\ncompose_prod egress-dez: a pilha fica de pe "
                f"(`docker compose -p {PROJECTO} down -v` para a derrubar)"
            )
        else:
            _compose(raiz, "down", "-v", "--remove-orphans", verificar=False)

    print()
    if falhas:
        for falha in falhas:
            print(f"compose_prod egress-dez: {falha}", file=sys.stderr)
        print(
            f"compose_prod egress-dez: {len(falhas)} falha(s) sobre "
            f"{len(DESTINOS)} destinos",
            file=sys.stderr,
        )
        return 1
    permitidos = sum(1 for d in DESTINOS if d["permitido"])
    print(
        f"compose_prod egress-dez: {len(DESTINOS)} destinos, {permitidos} permitidos "
        f"(**{alcancados} alcancados com 200**) e {len(DESTINOS) - permitidos} "
        "recusados com 403, cada recusa registada no access_log. De `data` nenhuma "
        f"ligacao passa; de `edge` passam {len(abertos_em_edge)} de {len(nomes)} "
        "directamente, por desenho e sem registo — so o `proxy-tls` e o `proxy-saida` "
        "podem estar la, e e o lint que o garante."
    )
    return 0
