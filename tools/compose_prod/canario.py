"""O canario do `compose_prod`: a prova de que o lint morde.

Um lint que passa nao diz se morde. Este repositorio ja pagou duas vezes por
confiar num verde: o gate 9 esteve sete PRs sem nada que o provasse, e o
primeiro canario do gate 3b dava verde com a lista de casos vazia
(`docs/ci.md` §3).

## Por mutacao, e nao por *fixtures*

A razao e a mesma que o `tools/env_lint/canario.py` escreve: as regras daqui
sao sobre **relacoes entre tres ficheiros** — o compose de producao, o manifesto
do conjunto reduzido e a allowlist do proxy. Uma *fixture* por regra nao e um
ficheiro, e uma arvore; trinta copias da arvore divergem da arvore real **sem
que nada avise**, e o canario passaria a verde sobre uma configuracao que ja
nao se parece com a que o gate verifica.

Por mutacao e o contrario: parte-se da arvore **real**, muda-se uma coisa, e
exige-se o achado. Prova-se que a regra morde **nesta** configuracao.

## As duas armadilhas desta forma, e como se fecham

1. **Uma mutacao que deixou de se aplicar.** A arvore muda, o texto que a
   mutacao trocava desaparece, e o caso passa a verde por nao ter medido nada.
   Dai cada mutacao ter de **encontrar o texto** que troca: se nao encontra,
   e falha com `nao se aplica`, nunca um verde.
2. **Vermelho pela regra errada.** Ser apanhada por outra regra qualquer e
   sorte, nao cobertura. Cada caso declara as regras que espera, e exige-se que
   os achados novos sejam **exactamente** essas.

E ha um terceiro fecho, o `MINIMO_POR_REGRA`: toda a regra de `lint.REGRAS` tem
de ter pelo menos um caso que a exercite. Uma regra nova sem canario falha o
canario — nao fica em silencio a espera de alguem repare.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import lint


class NaoSeAplica(RuntimeError):
    """A mutacao ja nao encontra o texto que ia trocar."""


class Copia:
    """A arvore copiada: so o que o `varrer` le."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz

    def ler(self, ficheiro: str) -> str:
        caminho = self.raiz / ficheiro
        if not caminho.is_file():
            raise NaoSeAplica(f"{ficheiro} nao existe")
        return caminho.read_text(encoding="utf-8")

    def escrever(self, ficheiro: str, texto: str) -> None:
        caminho = self.raiz / ficheiro
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto, encoding="utf-8", newline="\n")

    def trocar(self, ficheiro: str, padrao: str, novo: str, quantas: int = 1) -> None:
        """Troca `padrao` (expressao regular) por `novo`. Exige que bata."""
        texto = self.ler(ficheiro)
        resultado, encontradas = re.subn(
            padrao, novo.replace("\\", "\\\\"), texto, count=quantas, flags=re.MULTILINE
        )
        if encontradas != quantas or resultado == texto:
            raise NaoSeAplica(
                f"{ficheiro}: /{padrao}/ bateu {encontradas} vez(es) e esperavam-se "
                f"{quantas}"
            )
        self.escrever(ficheiro, resultado)

    def acrescentar(self, ficheiro: str, texto: str) -> None:
        self.escrever(ficheiro, self.ler(ficheiro).rstrip("\n") + "\n" + texto)

    def apagar(self, ficheiro: str) -> None:
        caminho = self.raiz / ficheiro
        if not caminho.is_file():
            raise NaoSeAplica(f"{ficheiro} nao existe")
        caminho.unlink()


@dataclass(frozen=True)
class Caso:
    codigo: str
    #: As regras que **tem** de disparar, e as unicas que podem.
    espera: frozenset[str]
    descricao: str
    mutacao: Callable[[Copia], None]
    #: Regras que podem ou nao disparar com esta mutacao, sem falhar o caso.
    #: Usa-se onde uma mutacao realista arrasta outra regra por consequencia, e
    #: cada uso tem a razao escrita no caso.
    tolera: frozenset[str] = field(default=frozenset())


# Um servico completo, para as mutacoes que precisam de acrescentar um. Esta
# aqui para que a mutacao mude **uma** coisa: um servico acrescentado sem
# `user`, `mem_limit` e `cpus` disparava quatro regras e nao provava nenhuma.
def _servico(nome: str, extra: str = "") -> str:
    """Um servico **completo e endurecido**, para a mutacao mudar uma coisa so.

    O `cap_drop` e o `security_opt` entraram depois: sem eles, acrescentar um
    servico disparava tambem `sem-cap-drop` e `sem-no-new-privileges`, e tres
    casos deixavam de provar o que diziam provar. Foi o proprio canario a
    apanha-lo, com a regra de «as regras que declarou, e so essas».
    """
    return f"""
  {nome}:
    image: caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d
    read_only: true
    user: "1000:1000"
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    networks:
      - app
    mem_limit: 512m
    cpus: 0.5
    healthcheck:
      test: ["CMD", "true"]
{extra}"""


def _casos_dos_consumidores() -> tuple[Caso, ...]:
    """KAM-187: um caso por processo e por defeito, mais os dois de *staging*.

    Por processo, as duas formas do defeito que o critério 1 nomeia:

    * **falta** — o `command:` do serviço passa a correr **outro** dos quatro.
      Nenhum serviço desaparece, nenhuma rede muda e o `conjunto` continua
      certo: só a regra nova vê que ninguém corre aquele processo;
    * **`server.ts`** — o `command:` passa a correr a sonda. Dispara as duas
      metades: o serviço corre o `server.ts`, e o processo dele ficou sem quem o
      corra.

    O de *staging* tira o `command:` por inteiro: é a forma exacta do defeito
    original, um serviço desta imagem a correr o `CMD`.
    """
    casos: list[Caso] = []
    for processo in lint.CONSUMIDORES:
        curto = processo.rsplit("/", 1)[1].removesuffix(".ts")
        outro = next(p for p in lint.CONSUMIDORES if p != processo)
        padrao = rf'"{re.escape(processo)}"'
        casos.append(
            Caso(
                f"consumidor-em-falta-{curto}",
                frozenset({"consumidor-em-falta"}),
                f"o servico de `{curto}` passa a correr outro processo, e ninguem "
                "corre o seu",
                lambda c, padrao=padrao, outro=outro: c.trocar(
                    lint.PROD, padrao, f'"{outro}"'
                ),
            )
        )
        casos.append(
            Caso(
                f"consumidor-com-server-ts-{curto}",
                frozenset({"consumidor-em-falta", "consumidor-com-server-ts"}),
                f"o servico de `{curto}` passa a correr o `server.ts`",
                lambda c, padrao=padrao: c.trocar(
                    lint.PROD, padrao, f'"{lint.SONDA_DO_WORKER}"'
                ),
            )
        )
    casos.append(
        Caso(
            "consumidor-sem-comando-em-staging",
            frozenset({"consumidor-em-falta", "consumidor-com-server-ts"}),
            "em *staging*, o servico do `entrada.ts` perde o `command:` e corre o "
            "`CMD` da imagem",
            lambda c: c.trocar(
                lint.STAGING,
                r'^    command: \["node", "services/worker-canal/src/entrada\.ts"\]\n',
                "",
            ),
        )
    )
    casos.append(
        Caso(
            "consumidor-atras-de-perfil",
            frozenset({"consumidor-em-falta"}),
            "o servico do `consumidor.ts` passa para tras de um perfil, e um "
            "arranque sem `--profile` nao o levanta",
            # Sem retro-referencia: o `trocar` escapa as barras do texto novo.
            lambda c: c.trocar(
                lint.PROD,
                r'^    command: \["node", "services/worker-canal/src/consumidor\.ts"\]$',
                '    profiles: ["consumidores"]\n'
                '    command: ["node", "services/worker-canal/src/consumidor.ts"]',
            ),
        )
    )
    return tuple(casos)


CASOS: tuple[Caso, ...] = (
    # ------------------------------------------------- criterio 1: conjunto
    Caso(
        "servico-nao-declarado",
        frozenset({"conjunto-servico-nao-declarado"}),
        "um servico novo no compose de producao sem passar pelo manifesto",
        lambda c: c.trocar(lint.PROD, r"^services:$", "services:" + _servico("intruso")),
    ),
    Caso(
        "servico-em-falta",
        frozenset({"conjunto-servico-em-falta"}),
        "um servico `presente` no manifesto desaparece do compose",
        # O `prometheus` e o escolhido porque nao declara destinos nem publica
        # portas: tirar outro arrastava `allowlist-*` ou `porta-publicada`.
        lambda c: c.trocar(lint.PROD, r"^  prometheus:$", "  prometheus-desligado:"),
        tolera=frozenset({"conjunto-servico-nao-declarado"}),
    ),
    Caso(
        "servico-pendente-presente",
        frozenset({"conjunto-servico-pendente-presente"}),
        "um servico `pendente` (Grafana, AGPL) aparece no compose de producao",
        lambda c: c.trocar(lint.PROD, r"^services:$", "services:" + _servico("grafana")),
    ),
    # ------------------------------------------------- criterio 1: denylist
    Caso(
        "denylist-minio",
        frozenset({"denylist"}),
        "o nome `minio` aparece no ficheiro de producao, num volume",
        lambda c: c.trocar(lint.PROD, r"^  prometheus-data:$", "  minio-data:"),
    ),
    Caso(
        "denylist-langfuse",
        frozenset({"denylist", "conjunto-servico-nao-declarado"}),
        "o Langfuse — que corre em *staging* — aparece em producao",
        lambda c: c.trocar(lint.PROD, r"^services:$", "services:" + _servico("langfuse")),
    ),
    Caso(
        "denylist-n8n",
        frozenset({"denylist"}),
        "o n8n aparece numa variavel de ambiente, e nao como servico",
        # A *denylist* le o texto todo e nao so os nomes dos servicos: e esta a
        # forma que um `services:` nao apanharia.
        lambda c: c.trocar(
            lint.PROD,
            r"^      LITELLM_LOCAL_MODEL_COST_MAP: \"True\"$",
            '      LITELLM_LOCAL_MODEL_COST_MAP: "True"\n'
            "      N8N_WEBHOOK_URL: http://n8n:5678/webhook",
        ),
    ),
    # -------------------------------------------------- criterio 2: imagens
    Caso(
        "imagem-por-etiqueta",
        frozenset({"imagem-por-etiqueta"}),
        "uma imagem passa a vir por etiqueta, sem `@sha256:`",
        lambda c: c.trocar(
            lint.PROD,
            r"image: prom/prometheus:v3\.7\.3@sha256:[0-9a-f]{64}",
            "image: prom/prometheus:v3.7.3",
        ),
        # O digest desaparece do compose de producao, e `staging` ainda o tem;
        # a regra de `staging` compara os dois sentidos e nao este.
        tolera=frozenset({"staging-com-outras-imagens"}),
    ),
    Caso(
        "imagem-nao-resolvida",
        frozenset({"imagem-nao-resolvida"}),
        "uma imagem depende de uma variavel sem omissao com digest",
        lambda c: c.trocar(
            lint.PROD,
            r"image: \$\{KAMBA_QUEUE_IMAGE:-valkey/valkey:[^}]+\}",
            "image: ${KAMBA_QUEUE_IMAGE}",
        ),
        tolera=frozenset({"staging-com-outras-imagens"}),
    ),
    # --------------------------------------------------- criterio 3: redes
    Caso(
        "rede-em-falta",
        # Renomear a rede faz as duas coisas, e as duas sao verdade: a `ops`
        # desaparece **e** aparece uma rede que nao e das quatro.
        frozenset({"rede-em-falta", "rede-nao-declarada"}),
        "a rede `ops` deixa de estar declarada",
        lambda c: c.trocar(lint.PROD, r"^  ops:$", "  ops-desligada:"),
    ),
    Caso(
        "data-com-rota",
        frozenset({"rede-com-rota"}),
        "a rede `data` deixa de ser `internal: true` e ganha rota para fora",
        lambda c: c.trocar(
            lint.PROD,
            r"^  data:\n    driver: bridge\n    internal: true$",
            "  data:\n    driver: bridge",
        ),
    ),
    Caso(
        "edge-sem-rota",
        frozenset({"rede-sem-rota"}),
        "a rede `edge` passa a `internal: true` e o proxy fica sem saida",
        lambda c: c.trocar(
            lint.PROD,
            r"^  edge:\n    driver: bridge$",
            "  edge:\n    driver: bridge\n    internal: true",
        ),
    ),
    Caso(
        "servico-em-edge",
        frozenset({"servico-em-edge"}),
        "o LiteLLM ganha `edge` e com ela um caminho de saida sem proxy",
        lambda c: c.trocar(
            lint.PROD,
            r"^    networks:\n      - app\n    mem_limit: 2048m\n    cpus: 1\.5$",
            "    networks:\n      - app\n      - edge\n    mem_limit: 2048m\n    cpus: 1.5",
        ),
    ),
    Caso(
        "dados-fora-de-data",
        frozenset({"dados-fora-de-data"}),
        "o Postgres ganha `app` e deixa de estar sem rota de saida",
        lambda c: c.trocar(
            lint.PROD,
            r"^    networks:\n      - data\n    mem_limit: 5120m$",
            "    networks:\n      - data\n      - app\n    mem_limit: 5120m",
        ),
    ),
    # --------------------------------------------------- criterio 3: egress
    Caso(
        "saida-sem-proxy",
        frozenset({"saida-sem-proxy"}),
        "quem declara destinos deixa de sair pelo proxy",
        lambda c: c.trocar(
            lint.PROD,
            r"^  HTTPS_PROXY: http://proxy-saida:3128$",
            "  HTTPS_PROXY: http://outro-caminho:3128",
        ),
    ),
    Caso(
        "allowlist-em-falta",
        frozenset({"allowlist-em-falta"}),
        "um destino declarado por um servico sai da allowlist do proxy",
        lambda c: c.trocar(
            lint.ALLOWLIST,
            r"^  - fqdn: graph\.facebook\.com$",
            "  - fqdn: graph.facebook.com.invalido",
        ),
        # Trocar o FQDN tira um destino **e** poe outro sem dono: as duas
        # metades da mesma mutacao, e as duas sao o defeito.
        tolera=frozenset({"allowlist-sem-dono"}),
    ),
    Caso(
        "allowlist-sem-dono",
        frozenset({"allowlist-sem-dono"}),
        "um destino entra na allowlist sem nenhum servico o declarar",
        lambda c: c.acrescentar(
            lint.ALLOWLIST,
            "  - fqdn: exfiltracao.exemplo.com\n"
            "    porta: 443\n"
            "    protocolo: https\n"
            "    razao: >-\n"
            "      Destino que nenhum servico declara — o defeito que o canario mede.\n"
            "    ticket: KAM-076\n",
        ),
    ),
    # -------------------------------------------- criterio 4: endurecimento
    Caso(
        "utilizador-root",
        frozenset({"utilizador-root"}),
        "um contentor passa a correr como root",
        lambda c: c.trocar(lint.PROD, r'^    user: "65534:65534"$', '    user: "0:0"'),
    ),
    Caso(
        "utilizador-por-omissao",
        frozenset({"utilizador-por-omissao"}),
        "um contentor deixa de declarar `user:` e corre com o da imagem",
        lambda c: c.trocar(lint.PROD, r'^    user: "65534:65534"\n', ""),
    ),
    Caso(
        "sem-limite-de-memoria",
        frozenset({"sem-limite-de-memoria"}),
        "um servico deixa de ter `mem_limit`",
        lambda c: c.trocar(lint.PROD, r"^    mem_limit: 1024m\n    cpus: 0\.5$", "    cpus: 0.5"),
    ),
    Caso(
        "sem-limite-de-cpu",
        frozenset({"sem-limite-de-cpu"}),
        "um servico deixa de ter `cpus`",
        lambda c: c.trocar(
            lint.PROD, r"^    mem_limit: 1024m\n    cpus: 0\.5$", "    mem_limit: 1024m"
        ),
    ),
    Caso(
        "capacidade-acrescentada",
        frozenset({"capacidade-acrescentada"}),
        "um servico acrescenta uma capacidade que ninguem nomeou",
        lambda c: c.trocar(
            lint.PROD,
            r"^    mem_limit: 1024m$",
            "    cap_add:\n      - SYS_ADMIN\n    mem_limit: 1024m",
        ),
    ),
    # ------------------------------------------------- as fugas de isolamento
    #
    # Os cinco casos seguintes nasceram de um **buraco medido**: a primeira
    # versao deste lint passava em silencio por todos eles. O `network_mode:
    # host` e o pior — um contentor com ele nao esta em rede nenhuma do
    # compose, pelo que as quatro redes do criterio 3 deixam de o conter, e o
    # guiao dos dez destinos continuaria verde porque mede o proxy e nao aquele
    # servico.
    Caso(
        "sem-cap-drop",
        frozenset({"sem-cap-drop"}),
        "o `cap_drop: ALL` e simplesmente apagado",
        lambda c: c.trocar(lint.PROD, r"^  cap_drop:\n    - ALL\n", ""),
    ),
    Caso(
        "sem-no-new-privileges",
        frozenset({"sem-no-new-privileges"}),
        "o `no-new-privileges` e apagado e um setuid volta a poder elevar",
        lambda c: c.trocar(lint.PROD, r"^  security_opt:\n    - no-new-privileges:true\n", ""),
    ),
    Caso(
        "fuga-privileged",
        frozenset({"fuga-de-isolamento"}),
        "um servico passa a `privileged: true`",
        lambda c: c.trocar(
            lint.PROD, r"^    mem_limit: 1024m$", "    privileged: true\n    mem_limit: 1024m"
        ),
    ),
    Caso(
        "fuga-network-mode",
        frozenset({"fuga-de-isolamento"}),
        "um servico sai das quatro redes com `network_mode: host`",
        lambda c: c.trocar(
            lint.PROD, r"^    mem_limit: 1024m$", "    network_mode: host\n    mem_limit: 1024m"
        ),
    ),
    # Os cinco casos seguintes vieram todos da **revisao adversarial**, que os
    # atravessou. O mais caro era o primeiro: o `mem_limit` e por contentor e a
    # soma contava-o uma vez por servico, pelo que o GWY reservava o dobro do
    # que o bloco propoe e o conjunto passava o tecto em 922 MiB **com o lint a
    # zero achados**.
    Caso(
        "replicas-divergentes",
        frozenset({"replicas-divergentes", "sem-duas-replicas"}),
        "as replicas do compose deixam de bater com as do manifesto",
        lambda c: c.trocar(lint.PROD, r"^      replicas: 2$", "      replicas: 3"),
    ),
    Caso(
        "memoria-por-contentor",
        frozenset({"memoria-divergente"}),
        "o `mem_limit` passa a ser o total do servico em cada replica",
        lambda c: c.trocar(
            lint.PROD, r"^    mem_limit: 256m\n    cpus: 1\.0$", "    mem_limit: 512m\n    cpus: 1.0"
        ),
    ),
    Caso(
        "tecto-alterado",
        frozenset({"tecto-alterado"}),
        "o tecto do criterio 4 e aberto numa linha de YAML",
        # A prova circular que a revisao encontrou: os dois lados da comparacao
        # vinham do mesmo ficheiro que a regra le.
        lambda c: c.trocar(lint.MANIFESTO, r"^fraccao_maxima_pct: 80$", "fraccao_maxima_pct: 95"),
    ),
    Caso(
        "rede-nao-declarada",
        frozenset({"rede-nao-declarada"}),
        "uma quinta rede, com rota, aparece no compose",
        lambda c: c.trocar(
            lint.PROD,
            r"^  ops:\n    driver: bridge\n    internal: true$",
            "  ops:\n    driver: bridge\n    internal: true\n  fuga:\n    driver: bridge",
        ),
    ),
    Caso(
        "no-proxy-aberto",
        frozenset({"no-proxy-aberto"}),
        "um `NO_PROXY: \"*\"` tira tudo do proxy de saida",
        lambda c: c.trocar(lint.PROD, r"^  NO_PROXY: localhost.*$", '  NO_PROXY: "*"'),
    ),
    Caso(
        "fuga-socket-do-docker",
        frozenset({"fuga-de-isolamento"}),
        "um servico monta o socket do Docker e com ele a maquina",
        lambda c: c.trocar(
            lint.PROD,
            r"^      - prometheus-data:/prometheus$",
            "      - prometheus-data:/prometheus\n      - /var/run/docker.sock:/var/run/docker.sock",
        ),
    ),
    Caso(
        "memoria-divergente",
        frozenset({"memoria-divergente"}),
        "o `mem_limit` de um servico deixa de ser o do manifesto",
        lambda c: c.trocar(lint.PROD, r"^    mem_limit: 1024m$", "    mem_limit: 128m"),
    ),
    Caso(
        "soma-de-memoria",
        frozenset({"soma-de-memoria", "memoria-divergente"}),
        "a soma dos limites passa os 80% da RAM do *host*",
        # O manifesto e a fonte da soma: subir um numero la e o defeito real
        # (alguem a dar folga a um servico sem olhar ao total), e arrasta a
        # divergencia face ao compose, que e a outra metade do mesmo erro.
        lambda c: c.trocar(lint.MANIFESTO, r"^    memoria_mib: 5120$", "    memoria_mib: 25600"),
    ),
    # ------------------------------------------ criterio 5: replicas, rotas
    Caso(
        "sem-duas-replicas",
        # Baixar as replicas no compose faz as duas: o criterio 5 pede 2, e o
        # manifesto (que a soma do criterio 4 usa) passa a discordar.
        frozenset({"sem-duas-replicas", "replicas-divergentes"}),
        "o GWY ou o AGR fica com uma replica so",
        lambda c: c.trocar(lint.PROD, r"^      replicas: 2$", "      replicas: 1"),
    ),
    Caso(
        "healthcheck-sem-healthz",
        frozenset({"healthcheck-sem-healthz"}),
        "a sonda de um servico de duas replicas deixa de chamar `/healthz`",
        lambda c: c.trocar(
            lint.PROD, r"fetch\('http://127\.0\.0\.1:3000/healthz'\)", "fetch('http://127.0.0.1:3000/')"
        ),
    ),
    Caso(
        "sem-healthcheck",
        frozenset({"sem-healthcheck"}),
        "um servico deixa de ter `healthcheck` e o *rolling* fica sem sinal",
        lambda c: c.trocar(
            lint.PROD,
            r"^    healthcheck:\n      test: \[\"CMD-SHELL\", \"wget -q -O /dev/null "
            r"http://127\.0\.0\.1:9090/-/healthy \|\| exit 1\"\]$",
            "    labels:\n      sem-sonda: sim",
        ),
    ),
    Caso(
        "porta-publicada",
        frozenset({"porta-publicada"}),
        "um servico que nao e o proxy TLS publica uma porta",
        lambda c: c.trocar(
            lint.PROD,
            r"^    networks:\n      - app\n    mem_limit: 2048m$",
            '    ports:\n      - "4000:4000"\n    networks:\n      - app\n    mem_limit: 2048m',
        ),
    ),
    Caso(
        "porta-que-nao-e-443",
        frozenset({"porta-publicada"}),
        "o proxy TLS publica uma porta externa que nao e a 443",
        # A porta **externa** e a que o criterio 5 nomeia; a interna e 8443
        # porque o binario do Caddy traz uma capacidade de ficheiro (ver o
        # `caddy/Caddyfile`). A mutacao troca a externa, que e o que conta.
        lambda c: c.trocar(lint.PROD, r'^      - "443:8443"$', '      - "8080:8443"'),
    ),
    Caso(
        "admin-sem-vpn",
        frozenset({"admin-sem-vpn", "conjunto-servico-pendente-presente"}),
        "o Grafana nasce com porta publicada em vez de so por VPN",
        # A sentinela do criterio 5. Hoje nao ha Grafana no compose: este caso
        # e a prova de que a regra morde no dia em que houver.
        lambda c: c.trocar(
            lint.PROD,
            r"^services:$",
            "services:" + _servico("grafana", '    ports:\n      - "3000:3000"\n'),
        ),
    ),
    # ------------------------------------------- ADR-001 e criterio 8
    Caso(
        "chatwoot-fala-com-a-meta",
        frozenset({"chatwoot-fala-com-a-meta"}),
        "o Chatwoot ganha credenciais da Meta e com elas um caminho proprio",
        lambda c: c.trocar(
            lint.PROD,
            r'^      DISABLE_ENTERPRISE: "true"$',
            '      DISABLE_ENTERPRISE: "true"\n      WHATSAPP_APP_ID: "123"',
        ),
    ),
    Caso(
        "flag-de-licenca",
        frozenset({"flag-de-licenca"}),
        "a edicao Enterprise do Chatwoot fica activa",
        lambda c: c.trocar(
            lint.PROD, r'^      DISABLE_ENTERPRISE: "true"$', '      DISABLE_ENTERPRISE: "false"'
        ),
    ),
    # ------------------------------------------------- criterio 2: staging
    Caso(
        "staging-ausente",
        frozenset({"staging-ausente"}),
        "o compose de *staging* desaparece",
        lambda c: c.apagar(lint.STAGING),
    ),
    Caso(
        "staging-com-outras-imagens",
        frozenset({"staging-com-outras-imagens"}),
        "*staging* deixa de correr a mesma imagem que producao",
        lambda c: c.trocar(
            lint.STAGING,
            r"image: prom/prometheus:v3\.7\.3@sha256:[0-9a-f]{64}",
            "image: prom/prometheus:v3.7.3"
            "@sha256:0000000000000000000000000000000000000000000000000000000000000000",
        ),
    ),
    Caso(
        "staging-sem-perfil-obs",
        frozenset({"staging-sem-perfil-obs", "langfuse-sem-perfil"}),
        "o perfil `staging-obs` desaparece e o Langfuse fica solto",
        lambda c: c.trocar(lint.STAGING, r"^      - staging-obs$", "      - outro-perfil"),
    ),
    Caso(
        "staging-obs-com-dados-reais",
        frozenset({"staging-obs-com-dados-reais"}),
        "*staging* passa a correr com `kamba_data_class=real`",
        lambda c: c.trocar(
            lint.STAGING,
            r"^      KAMBA_DATA_CLASS: \$\{KAMBA_DATA_CLASS:-synthetic\}$",
            "      KAMBA_DATA_CLASS: real",
        ),
    ),
    # ------------------------------- KAM-187: os quatro processos do worker
    *_casos_dos_consumidores(),
)

#: Toda a regra tem de ter canario. Um `lint.REGRAS` novo sem caso aqui falha o
#: canario — e nao fica em silencio a espera de que alguem repare.
#:
#: A chave e o nome da funcao da regra; o valor, os codigos de achado que ela
#: produz e que algum caso tem de exercitar.
MINIMO_POR_REGRA: dict[str, frozenset[str]] = {
    "r_conjunto": frozenset(
        {
            "conjunto-servico-nao-declarado",
            "conjunto-servico-em-falta",
            "conjunto-servico-pendente-presente",
        }
    ),
    "r_denylist": frozenset({"denylist"}),
    "r_imagens": frozenset({"imagem-por-etiqueta", "imagem-nao-resolvida"}),
    "r_redes_declaradas": frozenset(
        {"rede-em-falta", "rede-com-rota", "rede-sem-rota", "rede-nao-declarada"}
    ),
    "r_redes_por_servico": frozenset({"servico-em-edge", "dados-fora-de-data"}),
    "r_saida_pelo_proxy": frozenset(
        {"saida-sem-proxy", "allowlist-em-falta", "allowlist-sem-dono", "no-proxy-aberto"}
    ),
    "r_endurecimento": frozenset(
        {
            "utilizador-root",
            "utilizador-por-omissao",
            "sem-limite-de-memoria",
            "sem-limite-de-cpu",
            "capacidade-acrescentada",
            "sem-cap-drop",
            "sem-no-new-privileges",
            "fuga-de-isolamento",
        }
    ),
    "r_memoria": frozenset(
        {"memoria-divergente", "soma-de-memoria", "replicas-divergentes", "tecto-alterado"}
    ),
    "r_replicas_e_healthz": frozenset(
        {"sem-duas-replicas", "healthcheck-sem-healthz", "sem-healthcheck"}
    ),
    "r_portas": frozenset({"porta-publicada", "admin-sem-vpn"}),
    "r_meta_so_no_gwy": frozenset({"chatwoot-fala-com-a-meta"}),
    "r_flags_de_licenca": frozenset({"flag-de-licenca"}),
    "r_staging": frozenset(
        {
            "staging-ausente",
            "staging-com-outras-imagens",
            "staging-sem-perfil-obs",
            "staging-obs-com-dados-reais",
            "langfuse-sem-perfil",
        }
    ),
    "r_consumidores": frozenset({"consumidor-em-falta", "consumidor-com-server-ts"}),
}

#: O que se copia: so o que o `varrer` le. Copiar a arvore toda levava segundos
#: por caso e nao acrescentava nada — nenhuma regra le fora daqui.
_A_COPIAR = ("infra",)
_A_COPIAR_GLOB = ("services/*/egress.yaml",)


def _copiar(origem: Path, destino: Path) -> None:
    for parte in _A_COPIAR:
        if (origem / parte).is_dir():
            shutil.copytree(origem / parte, destino / parte)
    for padrao in _A_COPIAR_GLOB:
        for caminho in origem.glob(padrao):
            alvo = destino / caminho.relative_to(origem)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(caminho, alvo)


def correr(raiz: Path) -> tuple[list[str], dict[str, int]]:
    """Corre todos os casos. Devolve (falhas, numeros)."""
    falhas: list[str] = []
    exercitadas: set[str] = set()

    # A linha de base: a arvore real tem de estar limpa. Sem isto, um caso que
    # «da vermelho» podia estar a dar vermelho pelo que ja la estava.
    base, _ = lint.varrer(raiz)
    if base:
        return (
            [
                "a arvore real nao esta limpa, e o canario compara com ela: "
                + "; ".join(str(a) for a in base[:5])
            ],
            {"casos": len(CASOS), "cobertos": 0, "regras_exercitadas": 0,
             "regras": len(lint.REGRAS)},
        )

    for caso in CASOS:
        with tempfile.TemporaryDirectory(prefix="compose-prod-canario-") as pasta:
            destino = Path(pasta)
            _copiar(raiz, destino)
            copia = Copia(destino)
            try:
                caso.mutacao(copia)
            except NaoSeAplica as erro:
                falhas.append(
                    f"[{caso.codigo}] a mutacao nao se aplica ({erro}). Uma mutacao "
                    "que deixou de mudar nada e uma prova que deixou de existir."
                )
                continue
            try:
                achados, _ = lint.varrer(destino)
            except lint.ConfiguracaoInvalida as erro:
                # Saida 2 tambem e morder, mas nao e o que o caso declarou: um
                # ficheiro ilegivel esconde a regra que se queria provar.
                falhas.append(
                    f"[{caso.codigo}] a mutacao tornou a configuracao ilegivel "
                    f"({erro}); esperavam-se os achados {sorted(caso.espera)}"
                )
                continue
            regras = {a.regra for a in achados}
            exercitadas |= regras & caso.espera
            em_falta = caso.espera - regras
            a_mais = regras - caso.espera - caso.tolera
            if em_falta:
                falhas.append(
                    f"[{caso.codigo}] {caso.descricao}: nao disparou "
                    f"{sorted(em_falta)} (disparou {sorted(regras) or 'nada'})"
                )
            if a_mais:
                falhas.append(
                    f"[{caso.codigo}] {caso.descricao}: disparou tambem "
                    f"{sorted(a_mais)}, que o caso nao declarou. Ser apanhado por "
                    "outra regra e sorte, nao cobertura."
                )

    # O terceiro fecho: nenhuma regra sem canario.
    nomes = {regra.__name__ for regra in lint.REGRAS}
    for nome in sorted(nomes - set(MINIMO_POR_REGRA)):
        falhas.append(
            f"a regra `{nome}` nao esta em MINIMO_POR_REGRA: uma regra nova sem "
            "canario fica em silencio."
        )
    for nome in sorted(set(MINIMO_POR_REGRA) - nomes):
        falhas.append(
            f"`{nome}` esta em MINIMO_POR_REGRA e nao e uma regra de lint.REGRAS."
        )
    for nome, codigos in sorted(MINIMO_POR_REGRA.items()):
        if nome not in nomes:
            continue
        nao_provados = codigos - exercitadas
        if nao_provados:
            falhas.append(
                f"a regra `{nome}` tem os achados {sorted(nao_provados)} sem nenhum "
                "caso a prova-los."
            )

    numeros = {
        "casos": len(CASOS),
        "cobertos": len(CASOS) - len({f.split("]")[0].lstrip("[") for f in falhas if f.startswith("[")}),
        "regras_exercitadas": len(
            {nome for nome, codigos in MINIMO_POR_REGRA.items() if codigos & exercitadas}
        ),
        "regras": len(lint.REGRAS),
    }
    return falhas, numeros
