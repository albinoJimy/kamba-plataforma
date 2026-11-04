"""Como correr o condutor de TypeScript a partir da suite, e ler o que ele mediu.

As dezassete rotas de TypeScript do criterio 3 e as tres leituras por contacto
do criterio 6 vivem em Hono e em modulos de `services/*`. Uma aplicacao Hono
responde em processo pelo `app.request()` — sem servidor, sem porta, sem espera —
e e isso que torna o ataque deterministico. Mas o processo e `node`, e a suite e
Python; este modulo e a fronteira.

    relatorio = correr(
        "sondas",
        canarios={"platform.tenants": "canario_..."},
        tenant_a=a, tenant_b=b,
    )

## Porque e que isto nao reutiliza o `db/tests_identidade/node.py`

Esse ficheiro faz quase o mesmo e **nao serve**, por quatro razoes que se somam —
e nao por preferencia:

1. **O `cwd`.** Ele corre o `node` em `packages/core-ts`, porque e la que os
   testes de identidade vivem. O condutor importa de `services/com`, de
   `services/gwy` e de `services/worker-canal` por caminho relativo a **raiz do
   repositorio**, e e a resolucao a partir desses ficheiros que encontra o
   `hono` e o `@kamba/core-ts` de cada servico (o `pnpm` instala por pacote: a
   raiz do *workspace* tem o `typescript` e mais nada).
2. **Nao e importavel.** `db/` nao tem `__init__.py` e nao esta no `PYTHONPATH`
   do Makefile (`tools`, `libs/py-core/src` e `services/agr/src` estao). Um
   `from db.tests_identidade import node` nao importa, e por de la um
   `sys.path.insert` para chegar a uma constante era pior do que a declarar.
3. **As variaveis sao outras.** O `VARIAVEIS` dele e o ambiente da suite de
   identidade (`KAMBA_DB_NAME`, `POSTGRES_*`, as senhas dos tres papeis); o
   condutor le cinco `KAMBA_X01_*` e mais nada.
4. **A saida.** Ele passa o caminho por `KAMBA_IDENTIDADE_SAIDA`; o condutor
   recebe-o como segundo argumento da linha de comandos, porque um guiao que
   escreve um relatorio tem o caminho dele na invocacao.

O que **se** reutiliza e a forma: `node` do `PATH` quando existe, e a imagem
oficial fixada pelo digest quando nao existe — na rede do contentor da base,
para que ela esteja em `127.0.0.1:5432` sem publicar porta nenhuma. E a forma
que os oito `db/tests_*/node.py` desta casa ja usam, e a constante do digest
declara-se aqui como la: o inventario e o `ci/supply-chain/imagens.yaml`, e e
contra ele que o *gate* 11 a confere.

## O que este modulo nao faz

Nao julga o relatorio e nao o emenda. Se o condutor nao correr, **levanta** —
nunca devolve um dicionario vazio a fingir sucesso. Num *gate*, saltar e falhar,
e um `{}` devolvido em silencio era um caso de isolamento verde por nao ter
medido nada.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

#: `tools/isolamento/condutor/ponte.py` -> `tools/isolamento/condutor` ->
#: `tools/isolamento` -> `tools` -> a raiz.
RAIZ = Path(__file__).resolve().parents[3]

#: O guiao, relativo a raiz. E tambem o caminho que o `node` recebe, porque o
#: `cwd` **e** a raiz (ver o `docstring` do modulo).
GUIAO = "tools/isolamento/condutor/rotas.ts"

#: Os grupos que o condutor conhece. A lista esta aqui e nele, e as duas tem de
#: concordar: um grupo que so exista num dos lados e um caso que nunca corre.
GRUPOS = ("sondas", "webhook", "canais", "contacto")

#: A imagem usada quando nao ha `node` no `PATH`. A mesma versao de
#: `.node-version`, fixada pelo digest que `ci/supply-chain/imagens.yaml`
#: registra para ela (KAM-067). Declarada aqui como nos `db/tests_*/node.py`:
#: o inventario e a fonte, e esta constante e uma leitura dele.
IMAGEM_NODE = (
    "node:24.21.0-trixie-slim"
    "@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66"
)

#: Segundos. O condutor nao faz I/O de rede e as leituras por contacto sao tres
#: consultas por contacto; isto e folga para um *runner* lento a arrancar um
#: contentor, nao alvo.
TEMPO_MAXIMO = 150

#: O nome do contentor do PostgreSQL, posto por `db/gate_bd.py`.
VARIAVEL_DO_CONTENTOR = "KAMBA_GATE_CONTENTOR"

#: Onde vivem os `node_modules`, quando nao e na raiz do codigo que se testa (a
#: prova por mutacao corre sobre uma copia que nao os leva). A mesma variavel
#: que os `db/tests_*/node.py` leem, pela mesma razao.
VARIAVEL_DOS_MODULOS = "KAMBA_RAIZ_NODE_MODULES"


class SemNodeNemDocker(RuntimeError):
    """Nao ha `node` no `PATH` nem `docker` para correr a imagem oficial."""


class SemContentor(RuntimeError):
    """Pediu-se uma base ao condutor e nao se sabe em que contentor ela esta."""


class CondutorFalhou(RuntimeError):
    """O condutor correu e nao deixou relatorio legivel."""


def _raiz_dos_modulos(raiz: Path) -> Path:
    return Path(os.environ.get(VARIAVEL_DOS_MODULOS) or raiz)


#: Onde e que o `node` procura os modulos, a partir dos ficheiros que o condutor
#: importa. **Nao e so a raiz**, e isso mediu-se: o `hono` e dependencia de cada
#: servico e o `pnpm` deixa-o em `services/<nome>/node_modules`, pelo que uma
#: arvore com `node_modules` so na raiz nao resolve o `import` de
#: `services/gwy/src/app.ts`. A prova por mutacao corre sobre uma **copia** da
#: arvore, e e la que isto conta.
ARVORES_DE_MODULOS = (
    Path("."),
    Path("packages/core-ts"),
    Path("packages/contracts"),
    Path("services/gwy"),
    Path("services/com"),
    Path("services/worker-canal"),
    Path("services/onboarding-web"),
)


def _ligar_modulos(raiz: Path) -> None:
    """Com `node` no `PATH` e os modulos noutra raiz, liga-os por atalho simbolico.

    Uma arvore sem `node_modules` proprios — a copia que a prova por mutacao
    constroi — recebe-os por atalho da arvore real, que o
    `KAMBA_RAIZ_NODE_MODULES` nomeia. Liga-se **cada** arvore de modulos e nao
    so a raiz, pela razao escrita em `ARVORES_DE_MODULOS`.

    Um atalho que nao se consiga criar nao e erro: no Windows sem modo de
    desenvolvedor, `symlink_to` precisa de privilegio. Nesse caso o `import`
    falha mais a frente e o condutor escreve `executado: false` com a nota, que
    e o que o corredor transforma num achado legivel — melhor do que uma
    excepcao de permissoes a meio da ponte.
    """
    origem = _raiz_dos_modulos(raiz)
    if origem == raiz:
        return
    for relativo in ARVORES_DE_MODULOS:
        alvo = origem / relativo / "node_modules"
        destino = raiz / relativo / "node_modules"
        if destino.exists() or not alvo.is_dir():
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            destino.symlink_to(alvo, target_is_directory=True)
        except OSError:
            continue


def _ambiente(
    canarios: dict[str, str],
    tenant_a: str,
    tenant_b: str,
    pg: dict[str, Any] | None,
    contactos: dict[str, Any] | None,
) -> dict[str, str]:
    """As cinco variaveis do condutor, por cima do ambiente do processo.

    **Valores no ambiente e nunca na linha de comandos**, pela razao que os
    `db/tests_*/node.py` escrevem: o `ps` de qualquer utilizador da maquina le
    um `argv`, e aqui passariam por ele a senha do PostgreSQL e os canarios.
    """
    ambiente = dict(os.environ)
    ambiente["KAMBA_X01_CANARIOS"] = json.dumps(canarios, ensure_ascii=False)
    ambiente["KAMBA_X01_TENANT_A"] = str(tenant_a)
    ambiente["KAMBA_X01_TENANT_B"] = str(tenant_b)
    # Ausente e **diferente** de vazio: o condutor trata a ausencia como «sem
    # base» e escreve `executado: false` com a nota. Uma cadeia vazia era um
    # JSON invalido a caminho de uma mensagem confusa.
    if pg is not None:
        ambiente["KAMBA_X01_PG"] = json.dumps(pg)
    else:
        ambiente.pop("KAMBA_X01_PG", None)
    if contactos is not None:
        ambiente["KAMBA_X01_CONTACTOS"] = json.dumps(contactos, ensure_ascii=False)
    else:
        ambiente.pop("KAMBA_X01_CONTACTOS", None)
    return ambiente


#: Os nomes que a imagem precisa de receber. So nomes: os valores vao no
#: ambiente do `subprocess`, e o `--env NOME` sem `=` manda o Docker ir buscar
#: o valor la.
VARIAVEIS = (
    "KAMBA_X01_CANARIOS",
    "KAMBA_X01_TENANT_A",
    "KAMBA_X01_TENANT_B",
    "KAMBA_X01_PG",
    "KAMBA_X01_CONTACTOS",
)


def _contentor() -> str:
    nome = os.environ.get(VARIAVEL_DO_CONTENTOR, "")
    if not nome:
        raise SemContentor(
            f"{VARIAVEL_DO_CONTENTOR} nao esta definida e o grupo pedido precisa "
            "da base. Sem `node` no PATH, o condutor corre na imagem oficial e "
            "**na rede do contentor do PostgreSQL** — e sem o nome dele nao ha "
            "rede onde o por. `python db/gate_bd.py` e quem define a variavel."
        )
    return nome


def _correr_com_node(
    grupo: str, saida: Path, raiz: Path, ambiente: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    _ligar_modulos(raiz)
    return subprocess.run(
        ["node", GUIAO, grupo, str(saida)],
        cwd=raiz,
        env=ambiente,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TEMPO_MAXIMO,
        check=False,
    )


#: A porta em que o PostgreSQL escuta **dentro** do contentor. O
#: `db/gate_bd.py` publica-a numa porta efemera do anfitriao, e e essa que vai
#: no `KAMBA_X01_PG`; de dentro da rede do contentor vale esta.
PORTA_DE_DENTRO = 5432


def _com_porta_de_dentro(ambiente: dict[str, str]) -> dict[str, str]:
    """O mesmo ambiente, com o `KAMBA_X01_PG` a apontar para a porta de dentro."""
    bruto = ambiente.get("KAMBA_X01_PG")
    if not bruto:
        return ambiente
    pg = json.loads(bruto)
    pg["host"] = "127.0.0.1"
    pg["port"] = PORTA_DE_DENTRO
    return {**ambiente, "KAMBA_X01_PG": json.dumps(pg)}


def _correr_na_imagem(
    grupo: str,
    saida: Path,
    raiz: Path,
    ambiente: dict[str, str],
    precisa_de_base: bool,
) -> subprocess.CompletedProcess[str]:
    comando = ["docker", "run", "--rm"]
    if precisa_de_base:
        # A rede do contentor da base, e nao uma rede nova: assim o
        # `127.0.0.1` do contentor **e** o servidor, sem publicar porta nenhuma
        # para fora.
        comando += ["--network", f"container:{_contentor()}"]
        # **E a porta tem de ser a de dentro, nao a publicada.** O
        # `db/gate_bd.py` poe no `KAMBA_X01_PG` o par `127.0.0.1:<porta
        # publicada no anfitriao>` — que e o que o Python usa —, e dentro do
        # *namespace* de rede do contentor essa porta nao escuta: so a 5432
        # escuta. Medido: `Error: connect ECONNREFUSED 127.0.0.1:55559` nas
        # quatro leituras do grupo `canais` e nas seis do `contacto`, com a
        # cablagem toda certa. Reescreve-se aqui, que e o unico sitio que sabe
        # que vai correr dentro da rede do contentor.
        ambiente = _com_porta_de_dentro(ambiente)
    # `as_posix()` e nao `str()`: no Windows um caminho com barras invertidas
    # (`C:\Jimy\…`) obriga o Docker a adivinhar onde acaba o lado de fora do
    # `--volume`, e a forma com barras normais (`C:/Jimy/…`) nao tem essa
    # ambiguidade. No Linux as duas formas sao a mesma cadeia.
    comando += [
        "--volume",
        f"{raiz.as_posix()}:/repo:ro",
        "--volume",
        f"{saida.as_posix()}:/saida",
        "--workdir",
        "/repo",
    ]
    modulos = _raiz_dos_modulos(raiz)
    if modulos != raiz:
        # **Cada arvore de modulos, e nao so a raiz.** O `hono` e dependencia de
        # cada servico e o `pnpm` deixa-o em `services/<nome>/node_modules`:
        # montar so a raiz deixava o `import` de `services/gwy/src/app.ts` sem
        # resolucao, e o condutor escrevia `executado: false` nas quatro rotas
        # que precisam dela. Medido ao correr a prova por mutacao, que trabalha
        # sobre uma **copia** da arvore — e e a copia que nao tem modulos
        # proprios. A lista e a mesma do `_ligar_modulos`, para que os dois
        # caminhos (com `node` no PATH e sem ele) vejam a mesma arvore.
        for relativo in ARVORES_DE_MODULOS:
            alvo = modulos / relativo / "node_modules"
            if not alvo.is_dir():
                continue
            # **O ponto de montagem tem de existir na arvore montada**, e e por
            # isso que esta linha existe: o `/repo` vai `:ro`, e o Docker nao
            # cria um directorio dentro de um *bind* de leitura para servir de
            # ponto de montagem — sai **125** («error in docker run») antes de o
            # `node` arrancar, e o condutor nao deixa relatorio nenhum. Medido:
            # os quatro grupos sairam 125 na copia que a prova por mutacao
            # constroi. A pasta cria-se **na copia**, que e nossa; a arvore real
            # nunca chega aqui, porque la `modulos == raiz`.
            (raiz / relativo / "node_modules").mkdir(parents=True, exist_ok=True)
            dentro = (relativo / "node_modules").as_posix()
            comando += ["--volume", f"{alvo.as_posix()}:/repo/{dentro}:ro"]
    for nome in VARIAVEIS:
        if nome in ambiente:
            comando += ["--env", nome]
    comando += [IMAGEM_NODE, "node", GUIAO, grupo, "/saida"]
    # `MSYS_NO_PATHCONV`: no Git Bash do Windows, sem isto, `/repo` e `/saida`
    # eram reescritos para caminhos do Windows antes de chegarem ao Docker.
    ambiente = {**ambiente, "MSYS_NO_PATHCONV": "1"}
    return subprocess.run(
        comando,
        env=ambiente,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TEMPO_MAXIMO,
        check=False,
    )


def correr(
    grupo: str,
    *,
    canarios: dict[str, str],
    tenant_a: str,
    tenant_b: str,
    pg: dict[str, Any] | None = None,
    contactos: dict[str, Any] | None = None,
    raiz: Path | None = None,
) -> dict:
    """Corre o condutor para um grupo e devolve o relatorio JSON descodificado.

    `grupo` e um de `GRUPOS`. `canarios` e `{rotulo: valor}` — os canarios de B,
    que o oraculo procura nas respostas. `pg` e `{host, port, user, password,
    database}` e so os grupos `canais` e `contacto` o usam; `contactos` e
    `{"x": {"id", "canarios"}, "y": {...}}` e so o grupo `contacto` o usa.

    Devolve sempre um dicionario com as chaves `rotas` e `contacto`. **Nunca
    devolve `{}`**: um relatorio que nao se conseguiu ler levanta
    `CondutorFalhou`, porque num *gate* um caso sem medicao e um caso vermelho e
    nao um caso que passou.
    """
    if grupo not in GRUPOS:
        raise ValueError(f"grupo desconhecido: {grupo!r} (ha {', '.join(GRUPOS)})")
    raiz = (raiz or RAIZ).resolve()
    ambiente = _ambiente(canarios, tenant_a, tenant_b, pg, contactos)
    # Os grupos que falam com a base: e isso que decide se faz falta a rede do
    # contentor. `pg is None` nos outros dois, e entao nao ha rede a pedir.
    precisa_de_base = pg is not None

    with tempfile.TemporaryDirectory(prefix="kamba-x01-") as pasta:
        saida = Path(pasta) / f"{grupo}.json"
        # **O ficheiro cria-se antes.** O `--volume ficheiro:/saida` do Docker
        # cria uma *pasta* no lado de dentro quando o lado de fora nao existe, e
        # o guiao falhava a escrever «e uma pasta» em vez de escrever o
        # relatorio.
        saida.touch()

        if shutil.which("node"):
            resultado = _correr_com_node(grupo, saida, raiz, ambiente)
        elif shutil.which("docker"):
            resultado = _correr_na_imagem(grupo, saida, raiz, ambiente, precisa_de_base)
        else:
            raise SemNodeNemDocker(
                "nao ha `node` no PATH nem `docker` para correr a imagem "
                f"{IMAGEM_NODE.split('@')[0]}. As dezassete rotas de TypeScript "
                "do criterio 3 e as tres leituras por contacto do criterio 6 "
                "correm em processo num `node`, e sem um dos dois este caso nao "
                "se mede — num gate, saltar e falhar."
            )

        bruto = saida.read_text(encoding="utf-8") if saida.exists() else ""

    if resultado.returncode != 0 or bruto.strip() == "":
        raise CondutorFalhou(
            f"o condutor do grupo {grupo!r} saiu com {resultado.returncode} e "
            f"{'nao deixou' if bruto.strip() == '' else 'deixou'} relatorio.\n"
            f"stdout: {resultado.stdout[-800:]}\n"
            f"stderr: {resultado.stderr[-800:]}"
        )
    try:
        relatorio = json.loads(bruto)
    except json.JSONDecodeError as erro:
        raise CondutorFalhou(
            f"o relatorio do grupo {grupo!r} nao e JSON: {erro}\n"
            f"primeiros 400 caracteres: {bruto[:400]}"
        ) from erro
    if not isinstance(relatorio, dict) or "rotas" not in relatorio:
        raise CondutorFalhou(
            f"o relatorio do grupo {grupo!r} nao tem a chave `rotas`: "
            f"{str(relatorio)[:400]}"
        )
    relatorio.setdefault("contacto", [])
    return relatorio
