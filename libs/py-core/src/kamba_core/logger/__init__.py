"""`kamba_core.logger` — o unico sitio por onde um servico Python escreve (KAM-068).

    from kamba_core.logger import instalar

    log = instalar("agr")
    log.info(outcome="service_started")
    log.error(tenant_id=tenant, tool="criar_pedido", outcome="recusado",
              error_code="stock_insuficiente", latency_ms=42)
    try:
        ...
    except Exception as erro:
        log.excepcao(erro, "callback_invalido", tenant_id=tenant)

Cada chamada escreve **uma linha JSON** com campos da *allowlist* de
`docs/tecnica/08` §7.3 e mais nenhum. O que nao esta na lista, ou nao tem a
forma fechada do seu campo, e **retirado** da linha e contado em
`log_field_rejected_total:<motivo>`; em modo estrito (`KAMBA_LOG_ESTRITO=1`, o
«modo de teste» do ticket) levanta `CampoRejeitado` e nao escreve nada.

Tres coisas que este modulo nunca faz:

- **Nunca regista uma mensagem.** Nao ha argumento posicional de texto: um que
  apareca e contado como `mensagem_livre` e deitado fora. Um erro regista-se por
  `error_code` e pela classe da excepcao (`excepcao`), nunca por `str(erro)` — a
  mensagem de uma biblioteca traz o que a fez falhar, e isso e o *payload*.
- **Nunca chama `str()` nem `repr()` sobre o que recebe.** Um valor do tipo
  errado e recusado sem lhe correr codigo.
- **Nunca levanta fora do modo estrito.** Um *logger* que levanta derruba o
  pedido que estava a registar; uma escrita falhada conta em
  `log_write_failed_total` e segue.

O que as bibliotecas escrevem pelo `logging` da biblioteca padrao, e as
excepcoes que ninguem apanha, passam pela ponte de `ponte.py` — que `instalar`
liga — e saem na mesma forma: nivel, servico, o nome do *logger* e a classe.
Nunca a mensagem, os argumentos, o `extra` ou o *traceback*.

O espelho em TypeScript e `packages/core-ts/src/logger/`. A politica (campos,
formas, motivos) esta em `politica.py`; o processo para acrescentar um campo,
em `docs/logs.md` §5.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys

from ..tenant_guard import Contadores
from .politica import (
    CAMPOS,
    CAMPOS_DE_CHAMADA,
    CAMPOS_RESERVADOS,
    METRICA_ESCRITA_FALHADA,
    METRICA_REJEITADOS,
    MOTIVO_DESCONHECIDO,
    MOTIVO_MENSAGEM,
    MOTIVO_RESERVADO,
    MOTIVO_VALOR,
    MOTIVOS,
    NIVEIS,
    VARIAVEL_ESTRITO,
    codigo_com_classe,
    id_opaco,
    mascarar_referencia,
    nome_legivel,
    validar,
    validar_svc,
)

__all__ = [
    "CAMPOS",
    "CAMPOS_DE_CHAMADA",
    "CAMPOS_RESERVADOS",
    "CONTADORES",
    "CampoRejeitado",
    "Logger",
    "METRICA_ESCRITA_FALHADA",
    "METRICA_REJEITADOS",
    "MOTIVOS",
    "NIVEIS",
    "ServicoInvalido",
    "VARIAVEL_ESTRITO",
    "id_opaco",
    "instalar",
    "mascarar_referencia",
]

#: Contadores do *logger*. So numeros; os nomes sao os de `politica.py`.
CONTADORES = Contadores()


class ServicoInvalido(ValueError):
    """O nome do servico nao tem a forma de um. A mensagem nao repete o valor."""


class CampoRejeitado(ValueError):
    """Modo estrito: a chamada trazia algo que nao pode ir para um *log*.

    A mensagem diz o motivo e, quando e legivel, o **nome** do campo. Nunca o
    valor.
    """

    def __init__(self, rejeicoes: list[tuple[str, str]]) -> None:
        self.rejeicoes = tuple(rejeicoes)
        partes = ", ".join(f"{motivo} ({nome})" for motivo, nome in rejeicoes)
        super().__init__(
            f"o logger recusou {len(rejeicoes)} elemento(s): {partes}. So entram "
            "campos da allowlist com a forma fechada de cada um (docs/logs.md)."
        )


_TS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")


def _agora() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(instante: datetime.datetime) -> str:
    """UTC, milissegundos, sufixo `Z` — o mesmo que `Date.toISOString()`."""
    if type(instante) is not datetime.datetime:
        raise TypeError("o relogio tem de devolver um datetime")
    utc = instante.astimezone(datetime.timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


class Logger:
    """Escreve linhas JSON com os campos da *allowlist* e mais nenhum."""

    def __init__(self, svc: str, *, destino=None, relogio=None, estrito=None) -> None:
        canonico = validar_svc(svc)
        if canonico is None:
            raise ServicoInvalido(
                "o nome do servico tem de ser minusculas, digitos e hifenes "
                "(ate 32 caracteres), como em docs/tecnica/09 §3.1"
            )
        self._svc = canonico
        self._destino = destino
        self._relogio = relogio or _agora
        if estrito is None:
            estrito = os.environ.get(VARIAVEL_ESTRITO, "") == "1"
        self._estrito = bool(estrito)

    @property
    def svc(self) -> str:
        return self._svc

    @property
    def estrito(self) -> bool:
        return self._estrito

    def tolerante(self) -> "Logger":
        """O mesmo *logger*, fora do modo estrito. E o que a ponte usa."""
        return Logger(self._svc, destino=self._destino, relogio=self._relogio, estrito=False)

    # Os parametros sao **so posicionais** (`/`). Sem isso, um campo chamado
    # `self`, `erro` ou `codigo` — nomes que um dicionario espalhado em
    # argumentos pode perfeitamente trazer — fazia a chamada levantar
    # `TypeError`, e um *logger* nao levanta.

    def debug(self, /, *posicionais, **campos) -> None:
        self.registar("debug", posicionais, campos)

    def info(self, /, *posicionais, **campos) -> None:
        self.registar("info", posicionais, campos)

    def warn(self, /, *posicionais, **campos) -> None:
        self.registar("warn", posicionais, campos)

    def error(self, /, *posicionais, **campos) -> None:
        self.registar("error", posicionais, campos)

    def excepcao(self, erro, codigo=None, /, *posicionais, **campos) -> None:
        """Regista um erro por `error_code` e classe. Nunca pela mensagem.

        Sem codigo a linha sai sem `error_code`: esquecer um argumento
        dentro de um `except` nao pode ser o que derruba o pedido.
        """
        campos = dict(campos)
        campos["error_code"] = codigo_com_classe(codigo, type(erro).__name__)
        self.registar("error", posicionais, campos)

    def registar(self, nivel, posicionais, campos) -> None:
        """A forma dinamica das chamadas acima; e por aqui que todas passam.

        E a porta sem tipos, e por isso e a que tem a rede: o que nao for uma
        rejeicao do modo estrito e levantar ca dentro — um relogio que falha,
        um objecto que mente sobre o que e — conta em `log_write_failed_total`
        e a chamada volta sem escrever. O *lint* proibe usa-la fora do *logger*.
        """
        try:
            self._registar(nivel, posicionais, campos)
        except CampoRejeitado:
            raise
        except Exception:
            CONTADORES.incrementar(METRICA_ESCRITA_FALHADA)

    def _registar(self, nivel, posicionais, campos) -> None:
        # So tipos **exactos** (`type(x) is str`), nunca `isinstance`: uma
        # subclasse de `str`, de `dict` ou de `list` pode redefinir `__eq__`,
        # `items` ou `__iter__`, e a validacao corria o codigo de quem chamou.
        rejeicoes: list[tuple[str, str]] = []
        if type(nivel) is not str or nivel not in NIVEIS:
            rejeicoes.append((MOTIVO_VALOR, "level"))
            nivel = "error"
        if type(posicionais) not in (list, tuple):
            posicionais = () if posicionais is None else (posicionais,)
        for _ in posicionais:
            rejeicoes.append((MOTIVO_MENSAGEM, "<posicional>"))

        if campos is None:
            campos = {}
        elif type(campos) is not dict:
            # Um texto, um numero ou uma lista no lugar dos campos: e a
            # mensagem livre de quem vem de `print("...")`.
            rejeicoes.append((MOTIVO_MENSAGEM, "<posicional>"))
            campos = {}

        aceites: dict[str, object] = {}
        for nome, valor in campos.items():
            if valor is None:
                continue
            if type(nome) is not str:
                rejeicoes.append((MOTIVO_DESCONHECIDO, nome_legivel(nome)))
            elif nome in CAMPOS_RESERVADOS:
                rejeicoes.append((MOTIVO_RESERVADO, nome))
            elif nome not in CAMPOS_DE_CHAMADA:
                rejeicoes.append((MOTIVO_DESCONHECIDO, nome_legivel(nome)))
            else:
                limpo = validar(nome, valor)
                if limpo is None:
                    rejeicoes.append((MOTIVO_VALOR, nome))
                else:
                    aceites[nome] = limpo

        if rejeicoes and self._estrito:
            raise CampoRejeitado(rejeicoes)
        for motivo, _nome in rejeicoes:
            CONTADORES.incrementar(f"{METRICA_REJEITADOS}:{motivo}")

        ts = _iso(self._relogio())
        if not _TS.fullmatch(ts):
            # Um relogio que nao devolve um instante: nao se escreve o que ele
            # devolveu no lugar da hora.
            raise ValueError("relogio invalido")
        linha: dict[str, object] = {
            "ts": ts,
            "level": nivel,
            "svc": self._svc,
        }
        for nome in CAMPOS_DE_CHAMADA:
            if nome in aceites:
                linha[nome] = aceites[nome]
        self._escrever(json.dumps(linha, separators=(",", ":"), ensure_ascii=True))

    def _escrever(self, texto: str) -> None:
        # Sem `try` proprio: um destino que falha levanta ate a rede de
        # `registar`, que conta em `log_write_failed_total` e segue. Sem destino
        # nao ha onde dizer que falhou; o que nao se faz e deixar a excepcao
        # subir ate ao pedido.
        destino = self._destino if self._destino is not None else sys.stdout
        destino.write(texto + "\n")
        destino.flush()


def instalar(svc: str, *, destino=None, relogio=None, estrito=None) -> Logger:
    """Cria o *logger* do servico e liga a ponte ao resto do processo.

    Depois disto, o `logging` da biblioteca padrao, os `warnings` e as excepcoes
    que ninguem apanha (no fio principal, noutros fios e em destrutores) saem
    pela mesma forma, sem mensagem nem *traceback*. Chama-se uma vez, no
    arranque.
    """
    from .ponte import ligar

    registo = Logger(svc, destino=destino, relogio=relogio, estrito=estrito)
    ligar(registo)
    return registo
