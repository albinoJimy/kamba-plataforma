"""As regras do *lint* de backups — KAM-079.

Le **tres superficies que dizem o mesmo** e falha quando discordam:

    infra/backup/cobertura.yaml          os numeros e os predicados
    infra/backup/pgbackrest.conf         a configuracao do pgBackRest
    infra/backup/postgres-arquivo.conf   o arquivo de WAL

E mais duas, para os alertas:

    ops/metricas/catalogo.yaml                            o limite e o credor
    docs/runbooks/RB-K08-base-de-dados-e-restauro.md       o gatilho e a severidade

## PORQUE E QUE SAO CINCO E NAO UMA

Porque a divergencia entre elas **nao da erro em sitio nenhum hoje**. Um
`archive_timeout` de 60 s no `cobertura.yaml` e de 300 s no `.conf` passa por
todos os portoes deste repositorio: os dois ficheiros sao validos, nenhum
compilador os le, e o defeito so aparece em producao como um RPO que ninguem
prometeu. O mesmo vale para o limite do alerta do WAL, que esta escrito em
**quatro** sitios (aqui, no catalogo de metricas, no stub RB-K08 e no
`docs/tecnica/09` §9.2).

E a leitura do `tools/lint_contagens` e do `tools/compose_prod`: o erro de
conteudo aparece **a contar**, nao a ler.

## O QUE ESTE LINT NAO FAZ

Nao corre `pgbackrest check` nem `pgbackrest info`. Nao ha pgBackRest instalado
nesta maquina, nao ha `repo1` decidido (D1/KAM-105) e nao ha producao. Correr um
`check` contra um repositorio inexistente devolveria um erro de ligacao, e
registar isso como «verificado» era pior do que nao verificar. As duas caixas
que pedem aqueles dois comandos ficam **vazias**, com o credor.

Nao esta ligado a nenhum portao. O `cli.py` explica porque.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import kamba_yaml

#: A fonte unica dos numeros.
COBERTURA = "infra/backup/cobertura.yaml"

#: A configuracao do pgBackRest.
PGBACKREST = "infra/backup/pgbackrest.conf"

#: O fragmento do arquivo de WAL.
ARQUIVO = "infra/backup/postgres-arquivo.conf"

#: O catalogo de metricas do KAM-080, onde os dois alertas ainda vivem como
#: `regras_por_escrever`.
CATALOGO = "ops/metricas/catalogo.yaml"

#: Os runbooks.
RUNBOOKS = "docs/runbooks"

#: As tres bases que o criterio 1 nomeia. Fixas no codigo e **nao** lidas do
#: manifesto: um `cobertura.yaml` a que alguem apagasse a linha do `chatwoot`
#: nao pode dar «tudo verde».
BASES_EXIGIDAS = ("platform", "medusa", "chatwoot")

#: Os itens de cobertura que o bloco nomeia, alem das tres bases. Mesma razao.
ITENS_EXIGIDOS = (
    "objectos do STO",
    "configuracao em git",
    "exportacao cifrada do cofre",
    "ancora diaria do audit_log",
)

#: Os estados validos de uma linha de cobertura.
ESTADOS = ("coberto", "configurado", "por_cobrir")

#: Os estados que exigem credor nomeado. O `coberto` nao exige — nada falta —, e
#: por isso ele escreve `—` e nao um ticket.
ESTADOS_COM_CREDOR = ("configurado", "por_cobrir")

#: As severidades, as mesmas do `docs/tecnica/09` §9.2 e do `obs_lint`.
SEVERIDADES = ("P1", "P2", "P3")

#: A cifra que o criterio 1 exige: «repositorio cifrado AES-256». Aceita-se
#: qualquer modo AES-256 e **nenhuma** outra cifra — a regra e pelo prefixo e
#: nao por uma lista de nomes maus, pela razao do `ten/metricas.py`: uma lista
#: de proibidos protege contra os nomes de que alguem se lembrou; a forma
#: protege contra a forma.
PREFIXO_DA_CIFRA = "aes-256-"

#: Chaves que **nao podem aparecer** no `pgbackrest.conf`, em forma nenhuma —
#: nem com valor, nem com marcador.
#:
#: A primeira versao desta regra exigia o oposto: que cada uma destas chaves
#: estivesse presente **com** uma referencia `${NOME:?razao}`, na crenca de que
#: isso fazia a configuracao recusar-se a arrancar sem destino. A revisao
#: adversarial mediu que era falso, e o binario confirmou-o (pgBackRest 2.45):
#:
#:   ERROR: [032]: '${KAMBA_X:?razao}' must begin with / for 'repo1-path' option
#:
#: O pgBackRest nao expande variaveis dentro do ficheiro. O que ele tem e
#: `PGBACKREST_<OPCAO>` no ambiente, medido a funcionar na mesma versao. Pelo
#: que a regra passou a ser **ausencia**: a chave fora do ficheiro faz o
#: pgBackRest parar com «missing required option» se o ambiente tambem nao a
#: der, e essa recusa e dele e nao de uma convencao que ninguem implementa.
#:
#: A lista e fechada e literal, pela razao do inventario do `obs_lint`: um
#: filtro (por exemplo «toda a chave que acabe em `-pass`») deixava passar o
#: `repo1-host`, que nao e segredo mas e o destino que a D1 nao decidiu.
CHAVES_DO_AMBIENTE = (
    "repo1-cipher-pass",
    "repo1-host",
    "repo1-host-user",
    "repo1-path",
    "pg1-path",
    "pg1-database",
)

#: Das seis acima, as que sao **segredo** e por isso tem de estar no inventario.
#: As outras quatro sao valores de implantacao — um FQDN, um utilizador, dois
#: caminhos e um nome de base nao sao segredos, e tratar tudo como segredo faz o
#: inventario deixar de dizer o que protege.
CHAVES_QUE_SAO_SEGREDO = ("repo1-cipher-pass",)


def nome_no_ambiente(chave: str) -> str:
    """O `PGBACKREST_*` que corresponde a uma opcao, pela regra do pgBackRest.

    Derivado e nao tabelado de proposito: uma tabela escrita a mao divergia da
    chave no dia em que alguem renomeasse uma, e a divergencia nao daria erro.
    """
    return "PGBACKREST_" + chave.upper().replace("-", "_")

#: Os dois segredos que este ticket introduz, e que tem de estar no inventario.
SEGREDOS_DO_TICKET = ("backup_repo_cifra_passphrase", "backup_repo_credenciais")

#: O inventario de segredos.
INVENTARIO_DE_SEGREDOS = "ops/secrets-inventory.yaml"


class ConfiguracaoInvalida(Exception):
    """Uma superficie que nao se le. **Nao** e um achado: e a recusa de medir.

    A distincao e a do `obs_lint` e do `canon_lint`: um `cobertura.yaml` que nao
    se le nao pode parecer uma arvore conforme.
    """


@dataclass(frozen=True)
class Achado:
    regra: str
    onde: str
    mensagem: str

    def __str__(self) -> str:
        return f"[{self.regra}] {self.onde}: {self.mensagem}"


@dataclass(frozen=True)
class Dados:
    """O que se leu, uma vez, para todas as regras."""

    cobertura: dict
    pgbackrest: dict[str, str]
    arquivo: dict[str, str]
    catalogo: dict
    raiz: Path


# ---------------------------------------------------------------------------
# A leitura
# ---------------------------------------------------------------------------


def _ler_conf(caminho: Path, onde: str) -> dict[str, str]:
    """Um `.conf` de `chave=valor` ou `chave = valor`, com secoes em `[...]`.

    Nao e um parser de INI: aceita a forma que estes dois ficheiros usam e
    ignora secoes, porque nenhuma das chaves que interessam se repete entre
    secoes. Se alguma vier a repetir-se, a ultima ganha — e o `chave_repetida`
    falha antes disso.
    """
    if not caminho.is_file():
        raise ConfiguracaoInvalida(f"{onde} nao existe")
    pares: dict[str, str] = {}
    for numero, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
        texto = linha.strip()
        if not texto or texto.startswith("#") or texto.startswith("["):
            continue
        if "=" not in texto:
            raise ConfiguracaoInvalida(f"{onde}:{numero}: linha sem `=`: {texto!r}")
        chave, _, valor = texto.partition("=")
        chave = chave.strip()
        valor = valor.strip()
        if chave in pares:
            raise ConfiguracaoInvalida(
                f"{onde}:{numero}: `{chave}` repetida. A ultima ganharia em "
                "silencio, e um numero que se le duas vezes com valores "
                "diferentes nao e um numero"
            )
        pares[chave] = valor
    if not pares:
        raise ConfiguracaoInvalida(f"{onde}: zero chaves — isso nao e um zero util")
    return pares


def secoes_do_conf(caminho: Path) -> tuple[str, ...]:
    """Os nomes entre `[...]`. O `_ler_conf` ignora-os; a stanza vive num deles."""
    nomes = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        texto = linha.strip()
        if texto.startswith("[") and texto.endswith("]"):
            nomes.append(texto[1:-1])
    return tuple(nomes)


def ler(raiz: Path) -> Dados:
    caminho_cobertura = raiz / COBERTURA
    if not caminho_cobertura.is_file():
        raise ConfiguracaoInvalida(f"{COBERTURA} nao existe")
    try:
        cobertura = kamba_yaml.load_file(caminho_cobertura)
    except Exception as erro:  # noqa: BLE001 - a mensagem do leitor e a util
        raise ConfiguracaoInvalida(f"{COBERTURA}: {erro}") from erro
    if not isinstance(cobertura, dict):
        raise ConfiguracaoInvalida(f"{COBERTURA}: nao e um mapa")
    for chave in ("ciclo", "alvos", "cobertura", "alerta_do_wal", "restauro"):
        if chave not in cobertura:
            raise ConfiguracaoInvalida(f"{COBERTURA}: falta `{chave}`")

    caminho_catalogo = raiz / CATALOGO
    if not caminho_catalogo.is_file():
        raise ConfiguracaoInvalida(f"{CATALOGO} nao existe")
    try:
        catalogo = kamba_yaml.load_file(caminho_catalogo)
    except Exception as erro:  # noqa: BLE001
        raise ConfiguracaoInvalida(f"{CATALOGO}: {erro}") from erro

    return Dados(
        cobertura=cobertura,
        pgbackrest=_ler_conf(raiz / PGBACKREST, PGBACKREST),
        arquivo=_ler_conf(raiz / ARQUIVO, ARQUIVO),
        catalogo=catalogo if isinstance(catalogo, dict) else {},
        raiz=raiz,
    )


# ---------------------------------------------------------------------------
# As regras
# ---------------------------------------------------------------------------


def r_cifra(dados: Dados) -> list[Achado]:
    """Criterio 1: «repositorio cifrado AES-256», nas duas superficies."""
    achados: list[Achado] = []
    declarada = str(dados.cobertura["ciclo"].get("cifra", ""))
    if not declarada.startswith(PREFIXO_DA_CIFRA):
        achados.append(
            Achado(
                "cifra-fraca",
                COBERTURA,
                f"`ciclo.cifra` e `{declarada}` e o criterio 1 exige AES-256 "
                f"(prefixo `{PREFIXO_DA_CIFRA}`)",
            )
        )
    no_conf = dados.pgbackrest.get("repo1-cipher-type")
    if no_conf is None:
        achados.append(
            Achado(
                "cifra-fraca",
                PGBACKREST,
                "sem `repo1-cipher-type`: o pgBackRest **nao cifra por omissao**, "
                "e um repositorio em claro fora do host e o pior resultado deste "
                "ticket",
            )
        )
    elif not no_conf.startswith(PREFIXO_DA_CIFRA):
        achados.append(
            Achado(
                "cifra-fraca",
                PGBACKREST,
                f"`repo1-cipher-type={no_conf}` e o criterio 1 exige AES-256",
            )
        )
    elif no_conf != declarada:
        achados.append(
            Achado(
                "cifra-divergente",
                PGBACKREST,
                f"`repo1-cipher-type={no_conf}` e `{COBERTURA}` diz "
                f"`{declarada}`: duas superficies, dois valores",
            )
        )
    return achados


def r_segredo_em_claro(dados: Dados) -> list[Achado]:
    """As seis chaves do ambiente **ausentes** do ficheiro, e documentadas.

    Duas verificacoes, e a segunda e a que impede a primeira de ser inutil: uma
    chave ausente sem nada que diga de onde vem nao e uma configuracao segura, e
    um ficheiro onde ninguem sabe o que falta.
    """
    achados: list[Achado] = []
    texto = (dados.raiz / PGBACKREST).read_text(encoding="utf-8")
    for chave in CHAVES_DO_AMBIENTE:
        valor = dados.pgbackrest.get(chave)
        if valor is not None:
            e_segredo = chave in CHAVES_QUE_SAO_SEGREDO
            achados.append(
                Achado(
                    "segredo-em-claro" if e_segredo else "valor-de-implantacao",
                    PGBACKREST,
                    f"`{chave}` esta no ficheiro com o valor `{valor}`. Tem de "
                    f"estar **ausente** e vir do `{nome_no_ambiente(chave)}`: o "
                    "pgBackRest nao expande `${...}` dentro do ficheiro (medido, "
                    "«must begin with / for 'repo1-path' option»), pelo que um "
                    "marcador aqui e lido como valor"
                    + (
                        ". E o repositorio e publico"
                        if e_segredo
                        else ". Nao e segredo, mas e um valor que a D1 nao "
                        "decidiu, e um palpite escrito parece uma decisao"
                    ),
                )
            )
        if nome_no_ambiente(chave) not in texto:
            achados.append(
                Achado(
                    "ambiente-nao-documentado",
                    PGBACKREST,
                    f"`{chave}` nao esta no ficheiro e o cabecalho nao nomeia o "
                    f"`{nome_no_ambiente(chave)}`. Uma chave que falta sem dizer "
                    "de onde vem le-se como uma chave esquecida",
                )
            )
    return achados


def r_numeros_do_ciclo(dados: Dados) -> list[Achado]:
    """O ciclo, a retencao e o PITR nas duas superficies.

    A traducao de «35 dias» para «5 completos» e a parte que vale: o pgBackRest
    conta **backups**, nao dias, e sem o produto escrito ninguem ve que 5x7=35.
    """
    achados: list[Achado] = []
    ciclo = dados.cobertura["ciclo"]

    timeout = ciclo.get("archive_timeout_segundos")
    no_conf = dados.arquivo.get("archive_timeout")
    if no_conf is None:
        achados.append(
            Achado("chave-em-falta", ARQUIVO, "falta `archive_timeout`")
        )
    else:
        segundos = _segundos(no_conf)
        if segundos is None:
            achados.append(
                Achado(
                    "numero-ilegivel",
                    ARQUIVO,
                    f"`archive_timeout={no_conf}` nao se le como segundos",
                )
            )
        elif segundos != timeout:
            achados.append(
                Achado(
                    "ciclo-divergente",
                    ARQUIVO,
                    f"`archive_timeout` vale {segundos} s e `{COBERTURA}` diz "
                    f"{timeout} s. O criterio 1 escreve 60 s, e este numero e o "
                    "tecto do RPO antes do envio",
                )
            )

    if dados.arquivo.get("archive_mode") != "on":
        achados.append(
            Achado(
                "arquivo-desligado",
                ARQUIVO,
                "`archive_mode` nao e `on`: sem arquivo continuo nao ha PITR, e "
                "o criterio 1 pede «WAL continuo»",
            )
        )

    # O PITR. **A chave nao conta dias**: a documentacao do pgBackRest escreve
    # «Number of backups worth of continuous WAL to retain». A traducao para
    # dias so existe por causa do tipo e da cadencia, e e por isso que as tres
    # verificacoes abaixo sao uma so coisa partida em tres mensagens.
    pitr = ciclo.get("pitr_dias")
    tipo = dados.pgbackrest.get("repo1-retention-archive-type")
    arquivo_retido = _inteiro(dados.pgbackrest.get("repo1-retention-archive"))
    if arquivo_retido is None:
        achados.append(
            Achado(
                "chave-em-falta",
                PGBACKREST,
                "falta `repo1-retention-archive`: sem ela o pgBackRest faz a "
                "expiracao do arquivo cair no `repo1-retention-diff`/`-full` "
                "correspondente ao tipo, o que torna a janela de PITR um "
                "**efeito** de outra chave em vez de um numero declarado",
            )
        )

    if tipo != "diff":
        achados.append(
            Achado(
                "pitr-preso-ao-completo",
                PGBACKREST,
                f"`repo1-retention-archive-type={tipo}`: com `full`, o WAL e "
                "retido para os ultimos N backups **completos**, e com "
                "`repo1-retention-archive` acima do numero de completos retidos "
                "isso retem o WAL de todos eles — 35 dias de WAL e nao 7, que e "
                "**sobre-retencao contra o `docs/tecnica/08` §11**. Com `diff` e "
                "um diferencial diario, N diferenciais sao N dias",
            )
        )
    elif ciclo.get("diferencial") != "diario":
        # A traducao «7 backups = 7 dias» morre aqui, e nao no numero.
        achados.append(
            Achado(
                "pitr-sem-traducao",
                COBERTURA,
                f"`repo1-retention-archive={arquivo_retido}` conta "
                "**diferenciais**, e `ciclo.diferencial` nao e `diario`: sem a "
                f"cadencia diaria, {arquivo_retido} diferenciais nao sao "
                f"{pitr} dias e `pitr_dias` deixa de ser verificavel",
            )
        )
    elif arquivo_retido is not None and arquivo_retido != pitr:
        achados.append(
            Achado(
                "pitr-divergente",
                PGBACKREST,
                f"`repo1-retention-archive={arquivo_retido}` diferenciais, um "
                f"por dia, cobrem {arquivo_retido} dias, e `{COBERTURA}` pede "
                f"PITR de {pitr} dias",
            )
        )

    dias = ciclo.get("retencao_dias")
    completos_declarados = ciclo.get("retencao_completos")
    completos = _inteiro(dados.pgbackrest.get("repo1-retention-full"))
    if completos is None:
        achados.append(
            Achado("chave-em-falta", PGBACKREST, "falta `repo1-retention-full`")
        )
    elif completos != completos_declarados:
        achados.append(
            Achado(
                "retencao-divergente",
                PGBACKREST,
                f"`repo1-retention-full={completos}` e `{COBERTURA}` diz "
                f"{completos_declarados}",
            )
        )
    if (
        isinstance(dias, int)
        and isinstance(completos_declarados, int)
        and ciclo.get("completo") == "semanal"
        and completos_declarados * 7 != dias
    ):
        achados.append(
            Achado(
                "retencao-nao-reconcilia",
                COBERTURA,
                f"{completos_declarados} completos semanais cobrem "
                f"{completos_declarados * 7} dias e `retencao_dias` diz {dias}. "
                "O criterio 1 pede 35 dias",
            )
        )
    return achados


def r_comando_do_arquivo(dados: Dados) -> list[Achado]:
    """A **unica linha que invoca o pgBackRest**, e que ninguem lia.

    A revisao adversarial mediu aqui o defeito mais caro do ticket: o
    `archive_command` levava `--async`, que **nao e uma opcao do pgBackRest**, e
    as cinco superficies confrontavam o `archive_mode` e o `archive_timeout` sem
    nunca olhar para esta linha. Medido com o binario (pgBackRest 2.45):

        $ pgbackrest --stanza=k archive-push --async /tmp/x
        ERROR: [031]: invalid option '--async'

    O `archive_command` nunca devolveria 0, o Postgres nunca reciclaria WAL, e o
    sintoma chegaria como «o disco do Postgres encheu» — a falha de
    disponibilidade que este ficheiro existe para evitar.

    **A defesa e pela forma e nao por uma lista de nomes maus:** uma lista de
    opcoes proibidas protege contra `--async`, de que alguem se lembrou; uma
    lista de opcoes **permitidas** protege contra a proxima abreviatura que
    parece plausivel. O pgBackRest nao aceita abreviaturas.
    """
    #: As opcoes reais que esta linha pode levar. Fechada de proposito.
    permitidas = frozenset({"--stanza", "--config", "--archive-async"})
    achados: list[Achado] = []
    comando = dados.arquivo.get("archive_command")
    if comando is None:
        achados.append(
            Achado(
                "chave-em-falta",
                ARQUIVO,
                "falta `archive_command`: com `archive_mode = on` e sem comando, "
                "o Postgres nao recicla WAL e o `pg_wal` cresce ate o disco "
                "encher",
            )
        )
        return achados

    nu = comando.strip().strip("'\"")
    palavras = nu.split()
    if not palavras or "pgbackrest" not in palavras[0]:
        achados.append(
            Achado(
                "arquivo-sem-pgbackrest",
                ARQUIVO,
                f"`archive_command` nao invoca o pgBackRest: `{nu}`. O repo e "
                "cifrado e com retencao geridas por ele; um `cp` nao as tem",
            )
        )
    if "archive-push" not in palavras:
        achados.append(
            Achado(
                "arquivo-sem-archive-push",
                ARQUIVO,
                f"`archive_command` nao chama `archive-push`: `{nu}`",
            )
        )
    if "%p" not in palavras:
        achados.append(
            Achado(
                "arquivo-sem-caminho",
                ARQUIVO,
                "`archive_command` nao passa `%p`: sem o caminho que o Postgres "
                "da, o comando nao sabe que segmento empurrar",
            )
        )

    for palavra in palavras:
        if not palavra.startswith("--"):
            continue
        nome = palavra.split("=", 1)[0]
        if nome not in permitidas:
            achados.append(
                Achado(
                    "arquivo-com-opcao-inexistente",
                    ARQUIVO,
                    f"`archive_command` leva `{nome}`, que nao esta entre as "
                    f"opcoes reais desta linha ({', '.join(sorted(permitidas))}). "
                    "O pgBackRest recusa opcoes que nao conhece e **nao aceita "
                    "abreviaturas**: medido, `--async` da «invalid option» e o "
                    "arquivo nunca funciona. O modo assincrono liga-se com "
                    "`archive-async=y` no `pgbackrest.conf`, nao aqui",
                )
            )

    stanza = None
    for palavra in palavras:
        if palavra.startswith("--stanza="):
            stanza = palavra.split("=", 1)[1]
    if stanza is None:
        achados.append(
            Achado(
                "arquivo-sem-stanza",
                ARQUIVO,
                "`archive_command` nao diz `--stanza=`: sem ela o pgBackRest nao "
                "sabe para que repositorio empurrar",
            )
        )
    elif stanza not in secoes_do_conf(dados.raiz / PGBACKREST):
        achados.append(
            Achado(
                "arquivo-com-stanza-desconhecida",
                ARQUIVO,
                f"`archive_command` empurra para a stanza `{stanza}` e o "
                f"`{PGBACKREST}` nao a declara. Uma stanza que nao existe falha "
                "em funcionamento e nao ao arrancar",
            )
        )
    return achados


def r_repo_fora_do_host(dados: Dados) -> list[Achado]:
    """Criterio 7: «`repo1` noutro dominio de falha, fora do *host* primario».

    **Esta regra mudou de superficie, e a razao vale mais do que a regra.** A
    primeira versao lia o `repo1-host` e o `repo1-path` do `pgbackrest.conf`.
    Esses dois valores sairam do ficheiro para o ambiente
    (`PGBACKREST_REPO1_HOST`, `PGBACKREST_REPO1_PATH`), porque o pgBackRest nao
    expande marcadores — medido. Um valor que nao esta no repositorio **nao pode
    ser verificado por nada que viva no repositorio**, e finge-lo era pior do
    que admiti-lo.

    Logo a forma verifica-se onde o destino e **declarado como dado**: a lista
    `destinos` do `cobertura.yaml`. Hoje ela esta vazia (a D1 nao decidiu), pelo
    que esta regra nao morde em nada — e isso e o estado honesto, nao um verde.
    Morde no dia em que alguem escrever o primeiro destino, que e o dia em que
    o atalho «aponta para um caminho da propria maquina» se torna possivel.
    """
    achados: list[Achado] = []
    destinos = dados.cobertura.get("destinos") or []
    for destino in destinos:
        if not isinstance(destino, dict):
            continue
        nome = str(destino.get("nome", "?"))
        caminho = str(destino.get("caminho", ""))
        host = str(destino.get("host", ""))
        if not host:
            achados.append(
                Achado(
                    "repo-no-host-primario",
                    COBERTURA,
                    f"o destino `{nome}` nao declara `host`: um `caminho` sem "
                    "`host` e um caminho **da propria maquina**, e perder o host "
                    "perde a base e os backups — o defeito que o "
                    "`docs/tecnica/09` §8.1 corrige",
                )
            )
        if caminho.startswith("/var/lib/postgresql") or caminho.startswith("/pgdata"):
            achados.append(
                Achado(
                    "repo-no-pgdata",
                    COBERTURA,
                    f"o destino `{nome}` tem `caminho={caminho}`, dentro do "
                    "`PGDATA`: um repositorio no proprio volume de dados nao "
                    "sobrevive ao que se esta a proteger",
                )
            )
    return achados


def r_cobertura(dados: Dados) -> list[Achado]:
    """As tres bases e os quatro itens, cada um com estado valido e credor."""
    achados: list[Achado] = []
    linhas = dados.cobertura["cobertura"]
    if not isinstance(linhas, list) or not linhas:
        raise ConfiguracaoInvalida(f"{COBERTURA}: `cobertura` vazia")

    itens = {str(linha.get("item", "")) for linha in linhas if isinstance(linha, dict)}
    for base in BASES_EXIGIDAS:
        if f"base {base}" not in itens:
            achados.append(
                Achado(
                    "base-em-falta",
                    COBERTURA,
                    f"`base {base}` nao esta na cobertura. O criterio 1 nomeia as "
                    "tres, e uma que falte nao e um esquecimento visivel em "
                    "sitio nenhum",
                )
            )
    for item in ITENS_EXIGIDOS:
        if item not in itens:
            achados.append(
                Achado(
                    "item-em-falta",
                    COBERTURA,
                    f"`{item}` nao esta na cobertura, e os «Detalhes Tecnicos» "
                    "do bloco nomeiam-no",
                )
            )

    for linha in linhas:
        if not isinstance(linha, dict):
            raise ConfiguracaoInvalida(f"{COBERTURA}: item de cobertura que nao e mapa")
        item = str(linha.get("item", "?"))
        estado = str(linha.get("estado", ""))
        if estado not in ESTADOS:
            achados.append(
                Achado(
                    "estado-invalido",
                    COBERTURA,
                    f"`{item}` tem estado `{estado}`; os validos sao "
                    f"{', '.join(ESTADOS)}",
                )
            )
            continue
        if estado in ESTADOS_COM_CREDOR:
            credor = str(linha.get("credor", "")).strip()
            if not credor or credor in ("—", "-"):
                achados.append(
                    Achado(
                        "cobertura-sem-credor",
                        COBERTURA,
                        f"`{item}` esta `{estado}` e nao nomeia credor. Uma linha "
                        "que falta sem credor e trabalho que ninguem reclama",
                    )
                )
        if not str(linha.get("razao", "")).strip():
            achados.append(
                Achado(
                    "cobertura-sem-razao",
                    COBERTURA,
                    f"`{item}` nao escreve razao",
                )
            )
    return achados


def r_destinos(dados: Dados) -> list[Achado]:
    """Nenhum destino sem dono, e nenhum destino real sem `apd_ref`.

    E a regra do `infra/egress/proxy-saida.yaml` nos dois sentidos, aplicada ao
    repositorio de backup: um destino aprovado sem dono e o contrario de negar
    por omissao, e aqui custa mais do que la — o `repo1` recebe copias de bases
    inteiras.
    """
    from . import politica

    achados: list[Achado] = []
    destinos = dados.cobertura.get("destinos", [])
    if not isinstance(destinos, list):
        raise ConfiguracaoInvalida(f"{COBERTURA}: `destinos` nao e uma lista")

    for destino in destinos:
        if not isinstance(destino, dict):
            raise ConfiguracaoInvalida(f"{COBERTURA}: destino que nao e mapa")
        nome = str(destino.get("nome", "?"))
        for campo in ("fqdn", "jurisdicao", "dominio_de_falha", "credor", "ticket"):
            if not str(destino.get(campo, "") or "").strip():
                achados.append(
                    Achado(
                        "destino-sem-dono",
                        COBERTURA,
                        f"o destino `{nome}` nao declara `{campo}`. Um destino "
                        "aprovado sem dono e o contrario de negar por omissao",
                    )
                )
        veredicto = politica.pode_enviar(
            classe_de_dados="real",
            apd_ref=destino.get("apd_ref"),
            destino=nome,
        )
        if not veredicto.permitido and str(destino.get("classe_de_dados")) == "real":
            achados.append(
                Achado(
                    "destino-real-sem-apd-ref",
                    COBERTURA,
                    f"o destino `{nome}` esta marcado para dados `real` e "
                    f"{veredicto.razao}",
                )
            )

    por_decidir = dados.cobertura.get("destinos_por_decidir", [])
    if isinstance(por_decidir, list):
        for pendente in por_decidir:
            if not isinstance(pendente, dict):
                continue
            nome = str(pendente.get("nome", "?"))
            if not str(pendente.get("credor", "")).strip():
                achados.append(
                    Achado(
                        "destino-sem-dono",
                        COBERTURA,
                        f"o destino por decidir `{nome}` nao nomeia credor",
                    )
                )
    return achados


def r_alertas(dados: Dados) -> list[Achado]:
    """Os dois alertas: limite, severidade e runbook, cruzados com o catalogo.

    E a regra que vale mais, porque e a unica que apanha um defeito que **nenhum
    outro portao deste repositorio ve**: o limite do WAL esta escrito em quatro
    sitios, e mudar um deles nao produz erro em sitio nenhum.
    """
    achados: list[Achado] = []
    for chave in ("alerta_do_wal", "alerta_do_restauro"):
        alerta = dados.cobertura.get(chave)
        if not isinstance(alerta, dict):
            raise ConfiguracaoInvalida(f"{COBERTURA}: `{chave}` nao e um mapa")
        severidade = str(alerta.get("severidade", ""))
        if severidade not in SEVERIDADES:
            achados.append(
                Achado(
                    "severidade-invalida",
                    COBERTURA,
                    f"`{chave}.severidade` e `{severidade}`; as do "
                    f"`docs/tecnica/09` §9.2 sao {', '.join(SEVERIDADES)}",
                )
            )
        runbook = str(alerta.get("runbook", ""))
        encontrados = list((dados.raiz / RUNBOOKS).glob(f"{runbook}-*.md"))
        if not encontrados:
            achados.append(
                Achado(
                    "runbook-inexistente",
                    COBERTURA,
                    f"`{chave}.runbook` e `{runbook}` e nao ha "
                    f"`{RUNBOOKS}/{runbook}-*.md` no disco. A regra do §9.2 e "
                    "«alerta sem runbook e removido»",
                )
            )
        if not str(alerta.get("razao", "")).strip():
            achados.append(
                Achado("alerta-sem-razao", COBERTURA, f"`{chave}` nao escreve razao")
            )

    limite = dados.cobertura["alerta_do_wal"].get("limite_segundos")
    rpo = dados.cobertura.get("alvos", {}).get("rpo_segundos")
    if limite != rpo:
        achados.append(
            Achado(
                "limite-do-wal-divergente",
                COBERTURA,
                f"`alerta_do_wal.limite_segundos={limite}` e `alvos.rpo_segundos="
                f"{rpo}`. O alerta existe para disparar quando o RPO deixa de "
                "estar garantido: dois numeros diferentes querem dizer que ele "
                "dispara antes ou depois disso, e nenhum documento o diz",
            )
        )

    achados += _cruzar_com_o_catalogo(dados)
    return achados


def _cruzar_com_o_catalogo(dados: Dados) -> list[Achado]:
    """As duas entradas de `regras_por_escrever` que nomeiam o KAM-079.

    O catalogo do KAM-080 escreve, por entrada, o que **falta** e o **credor**.
    Este ticket muda o que falta: ja ha metrica declarada, e o que falta e um
    processo que a sirva. Uma entrada que continue a dizer «nao ha metrica de
    idade do WAL» depois deste ramo e prosa parada, e prosa parada sobre
    cobertura e pior do que nenhuma.
    """
    achados: list[Achado] = []
    regras = dados.catalogo.get("regras_por_escrever")
    if not isinstance(regras, list):
        raise ConfiguracaoInvalida(f"{CATALOGO}: sem `regras_por_escrever`")

    nossas = [
        r
        for r in regras
        if isinstance(r, dict) and "KAM-079" in str(r.get("credor", ""))
    ]
    if len(nossas) != 2:
        achados.append(
            Achado(
                "alertas-do-ticket-em-falta",
                CATALOGO,
                f"{len(nossas)} entrada(s) de `regras_por_escrever` com credor "
                "KAM-079, e o bloco tem dois alertas (WAL P1 e restauro P2)",
            )
        )
        return achados

    declaradas = {
        str(dados.cobertura["alerta_do_wal"].get("metrica")),
        str(dados.cobertura["alerta_do_restauro"].get("metrica")),
    }
    for regra in nossas:
        falta = str(regra.get("falta", ""))
        if not any(nome in falta for nome in declaradas):
            achados.append(
                Achado(
                    "falta-desactualizada",
                    CATALOGO,
                    f"a entrada «{regra.get('alerta')}» diz que falta «{falta}» e "
                    "nao nomeia nenhuma das metricas que este ramo declara "
                    f"({', '.join(sorted(declaradas))}). O que falta mudou: nao e "
                    "a metrica, e o processo que a serve",
                )
            )
    return achados


def r_segredos_no_inventario(dados: Dados) -> list[Achado]:
    """Os dois segredos do ticket estao em `ops/secrets-inventory.yaml`.

    Nao se le o inventario com o `kamba_yaml` para extrair os `id`: basta a
    presenca do nome, e a razao e de robustez — este *lint* nao deve ficar
    vermelho porque o esquema do inventario mudou noutro ticket. O que ele
    garante e que a chave de cifra do backup **nao e um segredo sem registo**,
    que e o defeito que importa: sem a chave o backup e inutil, e um segredo
    sem dono nao tem quem o rode nem quem lhe guarde a copia offline.
    """
    caminho = dados.raiz / INVENTARIO_DE_SEGREDOS
    if not caminho.is_file():
        raise ConfiguracaoInvalida(f"{INVENTARIO_DE_SEGREDOS} nao existe")
    texto = caminho.read_text(encoding="utf-8")
    return [
        Achado(
            "segredo-fora-do-inventario",
            INVENTARIO_DE_SEGREDOS,
            f"`{nome}` nao esta no inventario. Sem a chave de cifra o backup e "
            "inutil (`docs/tecnica/09` §8.1), e um segredo sem registo nao tem "
            "quem lhe guarde a copia offline",
        )
        for nome in SEGREDOS_DO_TICKET
        if nome not in texto
    ]


def r_restauro(dados: Dados) -> list[Achado]:
    """O periodo do restauro, e o agendador que falta dito em voz alta."""
    achados: list[Achado] = []
    restauro = dados.cobertura["restauro"]
    if not isinstance(restauro, dict):
        raise ConfiguracaoInvalida(f"{COBERTURA}: `restauro` nao e um mapa")
    periodo = restauro.get("periodo_dias")
    if not isinstance(periodo, int) or periodo <= 0:
        achados.append(
            Achado(
                "periodo-invalido",
                COBERTURA,
                f"`restauro.periodo_dias` e `{periodo}`: um periodo nao positivo "
                "faz o restauro estar sempre em divida",
            )
        )
    estado = str(restauro.get("agendador", ""))
    if estado not in ("ausente", "presente"):
        achados.append(
            Achado(
                "agendador-sem-estado",
                COBERTURA,
                f"`restauro.agendador` e `{estado}`; os valores sao `ausente` e "
                "`presente`",
            )
        )
    elif estado == "ausente" and not str(
        restauro.get("credor_do_agendador", "")
    ).strip():
        achados.append(
            Achado(
                "agendador-sem-credor",
                COBERTURA,
                "o agendador esta `ausente` e nao nomeia credor. «Mensal "
                "automatico» sem agendador e meia frase",
            )
        )
    return achados


REGRAS = (
    r_cifra,
    r_segredo_em_claro,
    r_numeros_do_ciclo,
    r_comando_do_arquivo,
    r_repo_fora_do_host,
    r_cobertura,
    r_destinos,
    r_alertas,
    r_segredos_no_inventario,
    r_restauro,
)


def varrer(raiz: Path) -> tuple[list[Achado], dict[str, int]]:
    """Todos os achados, e **quanto** se leu.

    O segundo valor nao e decoracao: um verde sobre zero linhas de cobertura
    le-se como «esta tudo bem». E a linha que o `compose_prod`, o `env_lint` e o
    `canon_lint` pagam pela mesma razao.
    """
    dados = ler(raiz)
    achados: list[Achado] = []
    for regra in REGRAS:
        achados += regra(dados)
    linhas = [l for l in dados.cobertura["cobertura"] if isinstance(l, dict)]
    numeros = {
        "itens": len(linhas),
        "cobertos": sum(1 for l in linhas if l.get("estado") == "coberto"),
        "configurados": sum(1 for l in linhas if l.get("estado") == "configurado"),
        "por_cobrir": sum(1 for l in linhas if l.get("estado") == "por_cobrir"),
        "destinos": len(dados.cobertura.get("destinos") or []),
        "destinos_por_decidir": len(dados.cobertura.get("destinos_por_decidir") or []),
        "chaves_do_pgbackrest": len(dados.pgbackrest),
        "chaves_do_arquivo": len(dados.arquivo),
        "regras": len(REGRAS),
    }
    return achados, numeros


# ---------------------------------------------------------------------------
# Leitores pequenos
# ---------------------------------------------------------------------------

_SUFIXOS = {"s": 1, "min": 60, "h": 3600, "ms": 0}


def _segundos(valor: str) -> int | None:
    """`60s`, `60`, `1min` — em segundos. `None` quando nao se le.

    O `ms` mapeia para 0 de proposito: um `archive_timeout` em milissegundos nao
    e um valor que este repositorio queira, e devolver 0 faz a comparacao com os
    60 falhar em vez de arredondar para um numero plausivel.
    """
    texto = valor.strip().strip("'\"")
    casa = re.match(r"^(\d+)\s*([a-z]*)$", texto)
    if not casa:
        return None
    quantidade = int(casa.group(1))
    sufixo = casa.group(2)
    if not sufixo:
        return quantidade
    if sufixo not in _SUFIXOS:
        return None
    return quantidade * _SUFIXOS[sufixo]


def _inteiro(valor: str | None) -> int | None:
    if valor is None:
        return None
    texto = valor.strip().strip("'\"")
    return int(texto) if texto.isdigit() else None
