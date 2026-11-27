"""Os ficheiros de segredos de cada servico de `prod` (KAM-260, ADR-L002 §1).

Decisao do fundador de 2026-11-27 (opcao B do bloco do KAM-260): o valor de um
segredo chega ao processo pelo **ambiente**, como o ADR-L002 decidiu, mas entra
no contentor por um **ficheiro** montado so de leitura, e nao pelo
`environment:` do compose — que o Docker grava no `Config.Env` do contentor e o
`docker inspect` mostra.

O que cada servico recebe declara-se no proprio compose, no bloco
`x-segredos:` do servico, com a mesma forma do `environment:`:

    x-segredos:
      KAMBA_SECRET_COM_INTERNAL_TOKEN: ${KAMBA_SECRET_COM_INTERNAL_TOKEN:?o cofre entrega o token}
      KAMBA_QUEUE_URL: redis://:${KAMBA_SECRET_QUEUE_PASSWORD:?...}@queue:6379

O compose interpola o bloco (um `:?` em falta continua a recusar o arranque),
mas um campo `x-` nao chega ao contentor. Este modulo le esses blocos,
interpola-os com o ambiente de quem o corre — o `doppler run --` do anfitriao —
e escreve `<destino>/<servico>.env`, modo `0400`, dono o UID do servico. O
`infra/compose/lancador/lancador.sh` carrega-o dentro do contentor e faz `exec`.

    doppler run -- python -m compose_prod segredos --destino /run/kamba/segredos

O destino e um `tmpfs` do anfitriao: os valores nunca vao a disco.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from supply_chain import arvore_yaml
from supply_chain import compose as compose_mod

from .lint import PROD, ConfiguracaoInvalida

#: O bloco do servico que declara o que vai no ficheiro.
CHAVE = "x-segredos"

#: Onde o ficheiro e o lancador ficam dentro do contentor.
FICHEIRO_NO_CONTENTOR = "/run/kamba/segredos.env"
LANCADOR_NO_CONTENTOR = "/run/kamba/lancador.sh"

#: Os utilizadores por nome que o compose de `prod` usa, com o UID que tem nas
#: imagens onde correm (as oficiais do Node e do Python em Debian). Um nome
#: fora daqui recusa-se: o ficheiro `0400` com o dono errado e um servico que
#: nao arranca.
UID_POR_NOME = {"root": 0, "node": 1000, "nobody": 65534}

#: `$$`, `${NOME}`, `${NOME:-x}`, `${NOME-x}`, `${NOME:?x}`, `${NOME?x}`, `$NOME`.
_INTERPOLACAO = re.compile(
    r"\$\$"
    r"|\$\{(?P<nome>[A-Za-z_][A-Za-z0-9_]*)(?:(?P<operador>:?[-?])(?P<resto>[^}]*))?\}"
    r"|\$(?P<simples>[A-Za-z_][A-Za-z0-9_]*)"
)


class SegredoEmFalta(ConfiguracaoInvalida):
    """Uma variavel exigida com `:?` nao esta no ambiente."""


def interpolar(modelo: str, ambiente: dict[str, str]) -> str:
    """A interpolacao do compose, nas formas que o compose de `prod` usa.

    Recusa as que nao segue — `${A:+x}`, uma omissao com outra variavel dentro
    (`${A:-${B}}`), um `$` solto —: o compose da-lhes um valor e este gravador
    escrevia o texto literal, e a prova de entrega do ensaio, que interpola com
    esta mesma funcao, ficava verde sobre o valor errado (revisao adversarial).
    """
    if "$" in _INTERPOLACAO.sub("", modelo):
        raise ConfiguracaoInvalida(
            f"forma de interpolacao que o gravador nao segue em `{modelo}`: so "
            "`${NOME}`, `${NOME:-x}`, `${NOME-x}`, `${NOME:?x}`, `${NOME?x}`, `$NOME` e `$$`"
        )

    def trocar(correspondencia: re.Match) -> str:
        if correspondencia.group(0) == "$$":
            return "$"
        nome = correspondencia.group("nome") or correspondencia.group("simples")
        operador = correspondencia.group("operador") or ""
        resto = correspondencia.group("resto") or ""
        if "$" in resto:
            raise ConfiguracaoInvalida(
                f"`${{{nome}{operador}...}}` tem outra interpolacao dentro, que o "
                "gravador nao segue"
            )
        valor = ambiente.get(nome)
        vazio = valor is None or (operador.startswith(":") and valor == "")
        if operador in (":-", "-"):
            return resto if vazio else valor
        if operador in (":?", "?"):
            if vazio:
                # O nome da variavel e a mensagem do compose; nunca um valor.
                raise SegredoEmFalta(f"`{nome}` em falta: {resto}")
            return valor
        return "" if valor is None else valor

    return _INTERPOLACAO.sub(trocar, modelo)


def declarados(raiz: Path) -> dict[str, dict[str, str]]:
    """`x-segredos` de cada servico do compose de `prod`, por interpolar."""
    try:
        ficheiro = compose_mod.ler(raiz / PROD, raiz)
    except (OSError, arvore_yaml.YamlIlegivel) as excepcao:
        raise ConfiguracaoInvalida(f"{PROD}: ilegivel: {excepcao}") from excepcao
    documento = ficheiro.documento
    resultado: dict[str, dict[str, str]] = {}
    for servico, (_no, chaves) in ficheiro.servicos.items():
        no = chaves.get(CHAVE)
        if no is None:
            continue
        try:
            mapa = documento.mapa(documento.resolver(no))
        except arvore_yaml.YamlIlegivel as excepcao:
            raise ConfiguracaoInvalida(
                f"{PROD}: `{servico}.{CHAVE}` ilegivel: {excepcao}"
            ) from excepcao
        resultado[servico] = {
            nome: documento.resolver(filho).texto() for nome, filho in mapa.items()
        }
    return resultado


def utilizadores(raiz: Path) -> dict[str, int]:
    """O UID com que cada servico corre, do `user:` do compose."""
    ficheiro = compose_mod.ler(raiz / PROD, raiz)
    resultado: dict[str, int] = {}
    for servico, (_no, chaves) in ficheiro.servicos.items():
        no = chaves.get("user")
        if no is None:
            continue
        texto = ficheiro.documento.resolver(no).texto().split(":", 1)[0]
        if texto.isdigit():
            resultado[servico] = int(texto)
        elif texto in UID_POR_NOME:
            resultado[servico] = UID_POR_NOME[texto]
        else:
            raise ConfiguracaoInvalida(
                f"{PROD}: `{servico}` corre como `{texto}`, que nao tem UID conhecido "
                "em `segredos.UID_POR_NOME`"
            )
    return resultado


def _linha(nome: str, valor: str) -> str:
    # Aspas simples: o `.` do lancador nao expande nada dentro delas. Uma aspa
    # simples no valor fecha, escapa-se e reabre.
    return f"{nome}='" + valor.replace("'", "'\\''") + "'\n"


def conteudo(variaveis: dict[str, str]) -> str:
    return "".join(_linha(nome, valor) for nome, valor in sorted(variaveis.items()))


def escrever(
    raiz: Path,
    destino: Path,
    ambiente: dict[str, str],
    modo: int = 0o400,
    dono: bool = True,
) -> dict[str, Path]:
    """Escreve um ficheiro por servico e devolve onde.

    `dono`: com `True` o ficheiro fica do UID do servico (o `0400` so o deixa
    ler a ele), o que pede `root`; sem `root` recusa, em vez de escrever
    ficheiros que nenhum servico le. O ensaio corre sem root e passa `False`.

    O destino nunca e o repositorio: um `--destino "$VAR"` com a variavel vazia
    vale `.`, e os ficheiros iam para disco, ao lado do codigo.
    """
    if str(destino).strip() in ("", "."):
        raise ConfiguracaoInvalida("destino vazio: os ficheiros de segredos vao para um tmpfs")
    alvo, repositorio = destino.resolve(), raiz.resolve()
    if alvo == repositorio or repositorio in alvo.parents:
        raise ConfiguracaoInvalida(
            f"destino `{destino}` dentro do repositorio: os ficheiros de segredos vao "
            "para um tmpfs do anfitriao, e nunca para ao lado do codigo"
        )
    root = hasattr(os, "geteuid") and os.geteuid() == 0
    if dono and not root:
        raise ConfiguracaoInvalida(
            "o gravador corre como root, para dar cada ficheiro ao UID do seu servico; "
            "sem isso o `0400` fica de quem o correu e nenhum servico o le"
        )
    por_servico = declarados(raiz)
    if not por_servico:
        raise ConfiguracaoInvalida(f"{PROD}: nenhum servico declara `{CHAVE}`")
    uids = utilizadores(raiz)
    # Interpola tudo antes de escrever o primeiro: um segredo em falta nao deixa
    # metade dos ficheiros escritos.
    textos = {
        servico: conteudo({nome: interpolar(modelo, ambiente) for nome, modelo in variaveis.items()})
        for servico, variaveis in por_servico.items()
    }
    destino.mkdir(parents=True, exist_ok=True)
    escritos: dict[str, Path] = {}
    for servico, texto in sorted(textos.items()):
        final = destino / f"{servico}.env"
        provisorio = destino / f".{servico}.env.novo"
        # `O_BINARY`: no Windows o `os.open` abre em modo de texto e escreve
        # `\r\n`, e o `\r` ficava no fim de cada valor (medido pela prova de
        # entrega do ensaio).
        bandeiras = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
        descritor = os.open(provisorio, bandeiras, modo)
        try:
            os.write(descritor, texto.encode("utf-8"))
        finally:
            os.close(descritor)
        os.chmod(provisorio, modo)
        if dono:
            os.chown(provisorio, uids.get(servico, 0), -1)
        os.replace(provisorio, final)
        escritos[servico] = final
    return escritos
