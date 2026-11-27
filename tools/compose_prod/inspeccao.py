"""O `docker inspect` dos servicos de `prod` ensaiado (KAM-260).

O `docs/adr/ADR-L002-injeccao-de-segredos.md` fixa que **nenhum valor de
segredo** entra num ficheiro de compose nem numa variavel declarada no
`environment:`, e por isso que o `docker inspect` de um contentor de `prod` nao
mostra valores (Consequencias). Este ensaio faz desse limite uma medicao:

1. gera um valor de **teste** por segredo do `ops/secrets-inventory.yaml` (e um
   para a segunda posicao do anel), aleatorio e so desta execucao — nada disto
   se versiona, e nunca se le um valor de `staging` nem de `prod`;
2. cria os contentores de **todos** os servicos do `docker-compose.prod.yml`,
   com todos os perfis, sob um projecto proprio;
3. corre o `docker inspect` de cada contentor e procura cada valor de teste em
   **toda** a saida (`Config.Env`, `Config.Cmd`, `Config.Entrypoint`,
   `Config.Labels`, montagens, *healthcheck*), e nao so no ambiente;
4. falha se algum aparecer, com o servico, o campo e o **nome** do segredo —
   nunca o valor.

## Criados e arrancados

O que o `docker inspect` mostra da configuracao de um contentor fixa-se quando
o contentor e **criado**, e por isso cria-se a pilha inteira sem a arrancar:
dispensa a base, a fila e as dependencias de cada servico. Depois, cada servico
que recebe segredos **arranca** um contentor seu (`docker compose run`, com o
`user:`, as montagens e as redes do servico), que corre o `lancador.sh` e uma
sonda que diz, por SHA-256, se cada segredo declarado chegou ao ambiente do
processo com o valor certo — um verde sem isto podia ser so um compose que
deixou de os entregar. Esses contentores tambem se inspeccionam.

O `entrypoint` da prova e o lancador sem o `entrypoint` original da imagem
(que a imagem substituta nao tem): a cadeia inteira prova-se a parte, com as
imagens reais (bloco do KAM-260 no EPIC-08, «Verificação»), e a forma dela fixa-a o
`tests/test_inspeccao.py`.

## Porque uma imagem substituta

As imagens dos nossos servicos ainda sao por `build:` (o `release.lock` e do
KAM-078), e as de terceiros pedem rede para se puxarem. O ensaio troca a imagem
de cada servico por uma que o inventario de imagens ja fixa
(`egress_dez.IMAGEM_SONDA`), e mantem **tudo o resto** do compose: ambiente,
comando, etiquetas, montagens, redes. O que fica fora e o ambiente que vem da
**imagem** (`ENV` de um `Dockerfile`), que e das imagens publicadas e do
registo — fora do ambito do KAM-260 e do KAM-078 (o gate 9 varre a imagem).

Codigo de saida: 0 limpo, 1 algum valor de segredo visivel, 2 o ensaio nao
conseguiu medir (Docker ausente, compose que nao se le, zero contentores).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import segredos
from .egress_dez import IMAGEM_SONDA
from .lint import PROD, ConfiguracaoInvalida

#: Projecto proprio: nao toca na pilha de mais ninguem nesta maquina.
PROJECTO = "kamba-prod-inspeccao"

INVENTARIO = "ops/secrets-inventory.yaml"

#: Quantas provas de entrega correm ao mesmo tempo.
PARALELO = 6

#: Prefixo dos nomes de variavel que o ADR-L002 §2 fixa.
PREFIXO = "KAMBA_SECRET_"

#: `${NOME` ou `${NOME:?mensagem}` / `${NOME:-omissao}` no texto do compose.
_VARIAVEL = re.compile(r"\$\{([A-Za-z][A-Za-z0-9_]*)(?::?([?-])([^}]*))?\}")

#: Uma entrada do inventario: `  - id: nome` no inicio da linha.
_ID = re.compile(r"^  - id: ([a-z0-9_]+)\s*$", re.MULTILINE)

#: «o deploy passa a cadeia de ligacao do kamba_app» -> `db_app_password`.
_PAPEL_DA_LIGACAO = re.compile(r"\bkamba_([a-z]+)\b")


@dataclass(frozen=True)
class Achado:
    servico: str
    contentor: str
    campo: str
    segredo: str

    def __str__(self) -> str:
        return (
            f"`{self.servico}` ({self.contentor}): o valor de teste de `{self.segredo}` "
            f"aparece no `docker inspect`, em `{self.campo}`"
        )


def valor_de_teste() -> str:
    """Um valor aleatorio desta execucao.

    Base32 e nao hexadecimal: um hex comprido casa por acaso a guarda de
    telefone de outros ensaios, e um valor de teste nao deve parecer outra
    coisa. Trinta e dois caracteres tornam impossivel um falso positivo por
    coincidencia com texto do compose.
    """
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def ids_do_inventario(raiz: Path) -> list[str]:
    """Os `id` do inventario, pela linha `- id:` de cada entrada.

    Le-se o texto e nao o YAML: o inventario usa listas em estilo de fluxo
    que o `kamba_yaml` nao le, e o leitor completo e o `secrets_inventory`,
    outra ferramenta. O que importa aqui e so a lista de nomes.
    """
    try:
        texto = (raiz / INVENTARIO).read_text(encoding="utf-8")
    except OSError as excepcao:
        raise ConfiguracaoInvalida(f"{INVENTARIO}: ilegivel: {excepcao}") from excepcao
    ids = _ID.findall(texto)
    if not ids:
        raise ConfiguracaoInvalida(f"{INVENTARIO}: zero segredos — o ensaio nao mediria nada")
    return ids


def variaveis_do_compose(texto: str) -> dict[str, tuple[str | None, str]]:
    """Cada `${NOME...}` do compose: o operador (`?`, `-` ou nenhum) e o texto."""
    vistas: dict[str, tuple[str | None, str]] = {}
    for nome, operador, resto in _VARIAVEL.findall(texto):
        anterior = vistas.get(nome)
        # Um `:?` ganha a um `:-` do mesmo nome: diz porque e obrigatorio.
        if anterior is None or (operador == "?" and anterior[0] != "?"):
            vistas[nome] = (operador or None, resto or "")
    return vistas


def ambiente_de_teste(
    ids: list[str], variaveis: dict[str, tuple[str | None, str]]
) -> tuple[dict[str, str], dict[str, str]]:
    """O ambiente com que se cria a pilha, e os valores a procurar.

    Devolve `(ambiente, procurar)`, com `procurar` a mapear cada valor de teste
    para o **nome** do segredo que o representa.
    """
    ambiente: dict[str, str] = {}
    procurar: dict[str, str] = {}

    for ident in ids:
        for sufixo, rotulo in (("", ident), ("_ANTERIOR", f"{ident} (anterior)")):
            valor = valor_de_teste()
            ambiente[f"{PREFIXO}{ident.upper()}{sufixo}"] = valor
            procurar[valor] = rotulo

    for nome, (operador, mensagem) in sorted(variaveis.items()):
        if nome in ambiente:
            continue
        if nome.startswith(PREFIXO):
            # Um segredo com instancia (`KAMBA_SECRET_<ID>__<instancia>`, ADR-L002
            # §2): o compose nomeia-o, e procura-se como `id/instancia`.
            ident, _, instancia = nome[len(PREFIXO):].partition("__")
            valor = valor_de_teste()
            ambiente[nome] = valor
            rotulo = ident.lower() + (f"/{instancia}" if instancia else "")
            if ident.lower() not in ids:
                rotulo += " (fora do inventario)"
            procurar[valor] = rotulo
            continue
        if nome.endswith("_DB_URL"):
            # A cadeia de ligacao leva a senha do papel que a mensagem nomeia.
            # Se o compose a expuser, o que aparece e a senha do inventario.
            papel = _PAPEL_DA_LIGACAO.search(mensagem)
            ident = f"db_{papel.group(1)}_password" if papel else "db_app_password"
            senha = ambiente.get(f"{PREFIXO}{ident.upper()}")
            if senha is None:
                senha = valor_de_teste()
                procurar[senha] = f"{nome} (fora do inventario)"
            ambiente[nome] = f"postgresql://kamba_ensaio:{senha}@postgres:5432/kamba"
            continue
        if operador == "?" and "cofre" in mensagem and not nome.endswith("_USER"):
            # Um valor que o compose diz vir do cofre e que o inventario nao
            # nomeia: procura-se tambem, com o nome da variavel.
            valor = valor_de_teste()
            ambiente[nome] = valor
            procurar[valor] = f"{nome} (fora do inventario)"
            continue
        if operador == "?":
            ambiente[nome] = "marcador"
    # O SHA da release e o que o `build:` pede; nao e segredo.
    ambiente.setdefault("KAMBA_COMMIT_SHA", "0" * 40)
    return ambiente, procurar


def _folhas(no: object, caminho: str):
    """Percorre o JSON do `docker inspect` e devolve `(caminho, texto)`."""
    if isinstance(no, dict):
        for chave, valor in no.items():
            sitio = f"{caminho}.{chave}" if caminho else str(chave)
            # A chave tambem: um caminho de `tmpfs:` ou o nome de uma etiqueta e
            # texto que o compose escreve no contentor (revisao adversarial).
            yield f"{sitio} (chave)", str(chave)
            yield from _folhas(valor, sitio)
    elif isinstance(no, list):
        for indice, valor in enumerate(no):
            if isinstance(valor, str) and caminho.endswith(".Env") and "=" in valor:
                # `NOME=valor`: o campo diz o nome da variavel, nunca o valor.
                yield f"{caminho}[{valor.split('=', 1)[0]}]", valor
            else:
                yield from _folhas(valor, f"{caminho}[{indice}]")
    elif isinstance(no, str):
        yield caminho, no


def procurar_valores(inspeccoes: list[dict], procurar: dict[str, str]) -> list[Achado]:
    """Os valores de teste que aparecem na saida do `docker inspect`."""
    achados: list[Achado] = []
    for inspeccao in inspeccoes:
        etiquetas = (inspeccao.get("Config") or {}).get("Labels") or {}
        servico = etiquetas.get("com.docker.compose.service", "?")
        contentor = str(inspeccao.get("Name", "?")).lstrip("/")
        for campo, texto in _folhas(inspeccao, ""):
            for valor, rotulo in procurar.items():
                if valor in texto:
                    achados.append(Achado(servico, contentor, campo, rotulo))
    return achados


# ----------------------------------------------------------------- execucao

#: O que corre dentro de cada servico, depois do lancador, para provar que os
#: segredos **chegam**: um verde sem isto podia ser so um compose que deixou de
#: os entregar. Imprime o SHA-256 de cada valor, e nunca o valor.
_SONDA_DE_ENTREGA = (
    "import hashlib, json, os, sys\n"
    "nomes = json.loads(sys.argv[1])\n"
    "print(json.dumps({n: hashlib.sha256(os.environ[n].encode()).hexdigest()"
    " if n in os.environ else None for n in nomes}))\n"
)

#: Os casos do canario: onde o ADR-L002 nao admite um valor, plantado de
#: proposito. Cada um diz o servico, o YAML que a sobreposicao lhe acrescenta,
#: o campo do `docker inspect` onde o valor tem de aparecer, e de que segredo.
CASOS_DO_CANARIO: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        "agr",
        ("    environment:",
         "      KAMBA_SECRET_COM_INTERNAL_TOKEN: ${KAMBA_SECRET_COM_INTERNAL_TOKEN:?canario}"),
        "Config.Env[KAMBA_SECRET_COM_INTERNAL_TOKEN]",
        "com_internal_token",
    ),
    (
        "prometheus",
        ("    environment:",
         "      KAMBA_CANARIO: ${KAMBA_SECRET_META_APP_SECRET:?canario}"),
        "Config.Env[KAMBA_CANARIO]",
        "meta_app_secret",
    ),
    (
        "gwy",
        ("    labels:",
         "      kamba.canario: ${KAMBA_SECRET_QUEUE_PASSWORD:?canario}"),
        "Config.Labels.kamba.canario",
        "queue_password",
    ),
    (
        "alertmanager",
        ('    command: ["--canario=${KAMBA_SECRET_DB_APP_PASSWORD:?canario}"]',),
        "Config.Cmd[0]",
        "db_app_password",
    ),
)


def _docker(*argumentos: str, env: dict[str, str] | None = None, verificar: bool = True):
    corrida = subprocess.run(
        ["docker", *argumentos], capture_output=True, text=True, check=False, env=env
    )
    if verificar and corrida.returncode != 0:
        # O `stderr` do Docker nomeia a variavel em falta, e nunca um valor.
        raise ConfiguracaoInvalida(
            f"`docker {' '.join(argumentos[:3])} ...` saiu com {corrida.returncode}: "
            f"{corrida.stderr.strip()[-800:]}"
        )
    return corrida


def _ambiente_do_processo(ambiente: dict[str, str]) -> dict[str, str]:
    base = {
        chave: valor
        for chave, valor in os.environ.items()
        # Nada do ambiente de quem corre o ensaio entra na pilha com nome de
        # segredo: so os valores gerados aqui.
        if not chave.startswith(PREFIXO)
    }
    base.update(ambiente)
    base["COMPOSE_PROFILES"] = "*"
    return base


def _sobreposicao(servicos: list[str], plantar: dict[str, tuple[str, ...]]) -> str:
    linhas = ["services:"]
    for servico in servicos:
        linhas += [
            f"  {servico}:",
            f'    image: "{IMAGEM_SONDA}"',
            "    build: !reset null",
            "    pull_policy: never",
            *plantar.get(servico, ()),
        ]
    return "\n".join(linhas) + "\n"


def _garantir_imagem() -> None:
    if _docker("image", "inspect", IMAGEM_SONDA, verificar=False).returncode != 0:
        _docker("pull", IMAGEM_SONDA)


def _entregas(
    comando: list[str], env: dict[str, str], ambiente: dict[str, str], raiz: Path,
    projecto: str,
) -> tuple[list[str], list[dict]]:
    """Corre a sonda dentro de cada servico, pelo lancador, e compara.

    Devolve as falhas e o `docker inspect` de cada contentor que **correu**: o
    ensaio inspecciona os contentores criados e tambem os arrancados.
    """
    uids = segredos.utilizadores(raiz)
    declarados = sorted(segredos.declarados(raiz).items())
    # Em paralelo: cada `docker compose run` cria e derruba um contentor, e em
    # serie as dezanove levavam mais de cinco minutos (medido).
    with ThreadPoolExecutor(max_workers=PARALELO) as executor:
        resultados = list(executor.map(
            lambda par: _entrega(comando, env, ambiente, uids, projecto, *par), declarados
        ))
    falhas = [falha for falhas_, _ in resultados for falha in falhas_]
    inspeccoes = [inspeccao for _, inspeccao in resultados if inspeccao is not None]
    return falhas, inspeccoes


def _entrega(
    comando: list[str], env: dict[str, str], ambiente: dict[str, str],
    uids: dict[str, int], projecto: str, servico: str, variaveis: dict[str, str],
) -> tuple[list[str], dict | None]:
    falhas: list[str] = []
    esperado = {
        nome: hashlib.sha256(segredos.interpolar(modelo, ambiente).encode()).hexdigest()
        for nome, modelo in variaveis.items()
    }
    nome_do_contentor = f"{projecto}-{servico}-entrega"
    try:
        corrida = _docker(
            *comando, "run", "--name", nome_do_contentor, "--no-deps", "-T",
            "--user", str(uids.get(servico, 0)),
            "--entrypoint", "/bin/sh", servico,
            segredos.LANCADOR_NO_CONTENTOR, "python", "-c", _SONDA_DE_ENTREGA,
            json.dumps(sorted(esperado)),
            env=env, verificar=False,
        )
        inspeccionado = _docker("inspect", nome_do_contentor, verificar=False)
    finally:
        _docker("rm", "-f", nome_do_contentor, verificar=False)
    try:
        (inspeccao,) = json.loads(inspeccionado.stdout)
    except (json.JSONDecodeError, ValueError):
        inspeccao = None
        falhas.append(f"`{servico}`: o contentor que correu nao se inspeccionou")
    try:
        visto = json.loads(corrida.stdout.strip().split("\n")[-1])
    except (json.JSONDecodeError, IndexError):
        falhas.append(
            f"`{servico}`: o lancador nao correu (saida {corrida.returncode}): "
            f"{corrida.stderr.strip()[-300:]}"
        )
        return falhas, inspeccao
    for nome in sorted(esperado):
        if visto.get(nome) is None:
            falhas.append(f"`{servico}`: `{nome}` nao chega ao ambiente do processo")
        elif visto[nome] != esperado[nome]:
            falhas.append(f"`{servico}`: `{nome}` chega com outro valor")
    return falhas, inspeccao


def medir(
    raiz: Path,
    plantar: dict[str, tuple[str, ...]] | None = None,
    entregas: bool = True,
    projecto: str = PROJECTO,
) -> tuple[list[Achado], list[str], dict[str, int]]:
    """Cria a pilha, inspecciona-a e derruba-a.

    Devolve `(achados, falhas_de_entrega, numeros)`. `plantar` acrescenta YAML
    a sobreposicao de um servico, e e por onde o canario planta um valor.
    """
    compose = raiz / PROD
    if not compose.is_file():
        raise ConfiguracaoInvalida(f"compose ausente: {PROD}")
    if shutil.which("docker") is None:
        raise ConfiguracaoInvalida("o ensaio do `docker inspect` precisa do Docker")

    ids = ids_do_inventario(raiz)
    ambiente, procurar = ambiente_de_teste(
        ids, variaveis_do_compose(compose.read_text(encoding="utf-8"))
    )
    _garantir_imagem()

    with tempfile.TemporaryDirectory(prefix="kamba-inspeccao-") as pasta:
        # Os ficheiros que o deploy escreveria, com os valores de teste. `0444`
        # e sem dono: o ensaio nao corre como root, e o UID do servico nao e o
        # de quem o corre. Em `prod` sao `0400` do UID do servico.
        ficheiros = Path(pasta) / "segredos"
        segredos.escrever(raiz, ficheiros, ambiente, modo=0o444, dono=False)
        ambiente = {**ambiente, "KAMBA_SEGREDOS_DIR": ficheiros.resolve().as_posix()}
        env = _ambiente_do_processo(ambiente)

        base = ["compose", "-f", str(compose)]
        servicos = _docker(*base, "config", "--services", env=env).stdout.split()
        if not servicos:
            raise ConfiguracaoInvalida("o compose de producao nao declara servicos")
        sobreposicao = Path(pasta) / "imagem-substituta.yml"
        sobreposicao.write_text(_sobreposicao(servicos, plantar or {}), encoding="utf-8")
        comando = [*base, "-f", str(sobreposicao), "-p", projecto]
        try:
            criado = _docker(*comando, "create", "--no-build", env=env, verificar=False)
            if criado.returncode != 0:
                raise ConfiguracaoInvalida(
                    f"`docker compose create` falhou: {criado.stderr.strip()[-800:]}"
                )
            ids_contentores = _docker(*comando, "ps", "-a", "-q", env=env).stdout.split()
            if not ids_contentores:
                raise ConfiguracaoInvalida("zero contentores criados — o ensaio nao mediu nada")
            inspeccoes = json.loads(_docker("inspect", *ids_contentores).stdout)
            falhas, corridos = (
                _entregas(comando, env, ambiente, raiz, projecto) if entregas else ([], [])
            )
            inspeccoes += corridos
        finally:
            _docker(
                *comando, "down", "-v", "--remove-orphans", env=env, verificar=False
            )

    achados = procurar_valores(inspeccoes, procurar)
    numeros = {
        "servicos": len(servicos),
        "contentores": len(inspeccoes),
        "arrancados": len(inspeccoes) - len(ids_contentores),
        "valores": len(procurar),
        "achados": len(achados),
        "com_ficheiro": len(segredos.declarados(raiz)),
    }
    return achados, falhas, numeros


def correr(raiz: Path) -> int:
    try:
        achados, falhas, numeros = medir(raiz)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as erro:
        print(f"compose_prod inspeccao: o ensaio nao mediu: {erro}", file=sys.stderr)
        return 2
    print(
        f"compose_prod inspeccao: {numeros['servicos']} servicos, "
        f"{numeros['contentores']} contentores inspeccionados "
        f"({numeros['arrancados']} arrancados pelo lancador), "
        f"{numeros['valores']} valores de teste procurados, "
        f"{numeros['com_ficheiro']} servicos com ficheiro de segredos"
    )
    for achado in achados:
        print(f"compose_prod inspeccao: {achado}", file=sys.stderr)
    for falha in falhas:
        print(f"compose_prod inspeccao: entrega: {falha}", file=sys.stderr)
    if numeros["com_ficheiro"] == 0:
        print("compose_prod inspeccao: nenhum servico com ficheiro de segredos", file=sys.stderr)
        return 2
    if achados or falhas:
        print(
            f"compose_prod inspeccao: {len(achados)} valores visiveis, "
            f"{len(falhas)} falhas de entrega",
            file=sys.stderr,
        )
        return 1
    print(
        "compose_prod inspeccao: 0 valores de segredo no `docker inspect`, e todos "
        "os segredos declarados chegam ao processo pelo lancador"
    )
    return 0


def canario(raiz: Path) -> int:
    """Prova que o ensaio morde: planta valores onde o ADR-L002 nao os admite."""
    plantar = {servico: linhas for servico, linhas, _campo, _segredo in CASOS_DO_CANARIO}
    try:
        achados, _falhas, _numeros = medir(raiz, plantar=plantar, entregas=False)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as erro:
        print(f"compose_prod inspeccao canario: nao mediu: {erro}", file=sys.stderr)
        return 2
    vistos = {(a.servico, a.campo, a.segredo) for a in achados}
    esperados = {(s, c, g) for s, _l, c, g in CASOS_DO_CANARIO}
    # Um valor plantado pode aparecer em mais de um campo — o do `command:`
    # aparece tambem no `Path` de topo do `docker inspect` (medido). O que nao
    # pode aparecer e um segredo que ninguem plantou: seria o compose a mostrar
    # um valor, e o canario so prova alguma coisa sobre um compose limpo.
    plantados = {(s, g) for s, _l, _c, g in CASOS_DO_CANARIO}
    falhas = [
        f"`{servico}`: o valor de `{segredo}` plantado em `{campo}` nao foi apanhado"
        for servico, campo, segredo in sorted(esperados - vistos)
    ]
    a_mais = sorted(v for v in vistos if (v[0], v[2]) not in plantados)
    falhas += [
        f"`{servico}`: `{segredo}` em `{campo}`, que nao foi plantado"
        for servico, campo, segredo in a_mais
    ]
    for falha in falhas:
        print(f"compose_prod inspeccao canario: {falha}", file=sys.stderr)
    print(
        f"compose_prod inspeccao canario: {len(esperados & vistos)} de "
        f"{len(CASOS_DO_CANARIO)} casos apanhados, {len(a_mais)} valores que nao foram plantados"
    )
    return 1 if falhas else 0
