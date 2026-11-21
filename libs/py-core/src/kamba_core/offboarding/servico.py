"""O processo das fases de dados do off-boarding (KAM-218, criterio 1).

O KAM-210 deixou o ciclo (`processo.correr_volta`) sem ninguem que o chamasse.
Este modulo e o que o `python -m kamba_core.offboarding` monta: le o ambiente,
abre o cofre, constroi as portas e corre a volta de `intervalo` em `intervalo`
segundos, com uma sonda `/healthz` para o *compose*. A decisao de cada fase
continua em `exportacao.py`, `purga.py` e `certificado.py`; aqui so se liga.

## O que este processo exige para arrancar, e porque nenhum tem omissao

* **As tres credenciais da base** — `kamba_batch` (as fases trancam e marcam
  como lote, `tenant_guard.tx_batch`), `kamba_app` (a exportacao le as
  coleccoes do tenant com o contexto dele, sob RLS) e `kamba_identity` (a purga
  apaga os contactos pelo cofre, `cofre.py`: o *crypto-shredding* do KAM-008, e
  so isso). Sem uma delas, um processo verde nao fazia nada: e o defeito do
  KAM-187.
* **O armazenamento** (KAM-011), pela configuracao do `storage.config` e pelas
  credenciais do cofre. Em `prod`, fora de Angola sem `apd_ref`, nao arranca
  (ADR-008) — essa recusa e do `ler_config`, e nao se repete aqui.
* **A chave do certificado**, `offboarding_certificate_key`, na forma
  `<kid>:<base64 de 32 octetos>` (KAM-205): o `kid` vai no certificado, e um
  valor sem `kid` recusa-se em vez de assinar com um rotulo posicional que muda
  na rotacao.
* **O ciclo das copias**, `KAMBA_OFFBOARDING_COPIAS_DIAS`. E o `retencao_dias`
  do `infra/backup/cobertura.yaml` (KAM-079), e o *compose* escreve-o; um ensaio
  confronta os dois. Um numero por omissao escrito aqui era uma segunda leitora
  do ciclo que ninguem actualiza quando ele muda.

## O que entra sem adaptador, e falha pelo nome

A entrega do certificado (`entrega_sem_adaptador`): nao ha agregador de SMS nem
fornecedor de e-mail escolhidos (fundador, KAM-116 e KAM-115). O certificado
fica `pendente` (a entrega levanta antes de qualquer gravacao), o alerta
`offboarding_fase_parada` dispara passado o prazo, e o *runbook*
(`docs/offboarding.md` §7) diz como o entregar a mao. A fonte do catalogo da Medusa
entra por argumento quando houver adaptador (a D3 por ratificar); sem ela a
exportacao di-lo no manifesto.
"""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Final

from ..health import healthz
from ..secrets.kid import separar_kid
from ..storage.config import StorageConfig, ler_config
from ..storage.port import StorageProvider
from .certificado import EntregarAoTitular
from .cofre import PAPEL_DO_COFRE, apagar_contactos_pelo_cofre
from .exportacao import FonteDoCatalogo
from .processo import PortasDosDados, ResultadoDaVolta, correr_volta, entrega_sem_adaptador
from .purga import ApagarContactos

#: O nome do servico, no `/healthz`, no registo e no `application_name`.
SERVICO: Final = "offboarding-dados"
VERSAO: Final = "0.1.0"

#: O ambiente, como o do IDX e do AGR.
VAR_AMBIENTE: Final = "KAMBA_ENV"
AMBIENTES: Final = ("dev", "staging", "prod")

#: As variaveis da base: as do IDX (`kamba_core/idx/__main__.py`), com dois papeis.
VAR_HOST: Final = "KAMBA_DB_HOST"
VAR_PORTA_DA_BASE: Final = "KAMBA_DB_PORT"
VAR_BASE: Final = "KAMBA_DB_NAME"
VAR_SENHA_APP: Final = "KAMBA_SECRET_DB_APP_PASSWORD"
VAR_SENHA_BATCH: Final = "KAMBA_SECRET_DB_BATCH_PASSWORD"
#: `kamba_identity` — so o apagamento dos contactos na purga (`cofre.py`).
VAR_SENHA_COFRE: Final = "KAMBA_SECRET_DB_IDENTITY_PASSWORD"

#: Os dois papeis. As fases sao do lote; a leitura das coleccoes na exportacao e
#: da aplicacao, com o contexto do tenant (`exportacao.exportar`).
PAPEL_DO_LOTE: Final = "kamba_batch"
PAPEL_DA_APP: Final = "kamba_app"

#: A sonda. Tem de coincidir com o *compose*.
VAR_PORTA: Final = "OFFBOARDING_DADOS_PORT"
PORTA_POR_OMISSAO: Final = 8062

#: Segundos entre voltas. **Proposta**: os 15 min do ciclo do lado TypeScript
#: (`LOTE_OFFBOARDING_INTERVALO_MS`), porque os prazos das fases sao em dias.
VAR_INTERVALO: Final = "KAMBA_OFFBOARDING_INTERVALO_S"
INTERVALO_POR_OMISSAO_S: Final = 900

#: Os dias do ciclo das copias de seguranca. **Obrigatoria**, sem omissao.
VAR_COPIAS: Final = "KAMBA_OFFBOARDING_COPIAS_DIAS"

#: O segredo que assina o certificado, e os do armazenamento.
SEGREDO_DO_CERTIFICADO: Final = "offboarding_certificate_key"
SEGREDOS_DO_ARMAZENAMENTO: Final = ("storage_access_key_id", "storage_secret_access_key")
SEGREDOS_OBRIGATORIOS: Final = (*SEGREDOS_DO_ARMAZENAMENTO, SEGREDO_DO_CERTIFICADO)


class ConfiguracaoEmFalta(RuntimeError):
    """Falta uma variavel, ou e invalida. A mensagem diz qual; nunca o valor."""


class ChaveDoCertificadoInvalida(RuntimeError):
    """A chave do certificado nao tem a forma `<kid>:<base64 de 32 octetos>`. Sem o valor."""

    def __init__(self) -> None:
        super().__init__(
            f"o segredo {SEGREDO_DO_CERTIFICADO} tem de ter a forma <kid>:<base64 de 32 octetos>"
        )


@dataclass(frozen=True)
class Configuracao:
    ambiente: str
    porta: int
    intervalo_s: int
    copias_dias: int
    armazenamento: StorageConfig


def _exigir(ambiente: Mapping[str, str], nome: str) -> str:
    valor = (ambiente.get(nome) or "").strip()
    if not valor:
        raise ConfiguracaoEmFalta(f"a variavel de ambiente {nome} nao esta definida (ou esta vazia)")
    return valor


def _inteiro(ambiente: Mapping[str, str], nome: str, omissao: int | None, minimo: int, maximo: int) -> int:
    bruto = (ambiente.get(nome) or "").strip()
    if not bruto:
        if omissao is None:
            raise ConfiguracaoEmFalta(f"a variavel de ambiente {nome} nao esta definida (ou esta vazia)")
        return omissao
    if not bruto.isdigit() or not minimo <= int(bruto) <= maximo:
        raise ConfiguracaoEmFalta(f"{nome} tem de ser um inteiro entre {minimo} e {maximo}")
    return int(bruto)


def ler_configuracao(ambiente: Mapping[str, str]) -> Configuracao:
    """A configuracao do processo, ou `ConfiguracaoEmFalta`. **Arranca em `prod`.**

    Exige as tres senhas da base aqui, e nao so quando a primeira ligacao abre:
    um processo que arranca verde e falha a cada volta e um processo que o
    *compose* da por saudavel.
    """
    nome_do_ambiente = _exigir(ambiente, VAR_AMBIENTE)
    if nome_do_ambiente not in AMBIENTES:
        raise ConfiguracaoEmFalta(f"{VAR_AMBIENTE} tem de ser um de {', '.join(AMBIENTES)}")
    for nome in (VAR_BASE, VAR_SENHA_APP, VAR_SENHA_BATCH, VAR_SENHA_COFRE):
        _exigir(ambiente, nome)
    porta = _inteiro(ambiente, VAR_PORTA, PORTA_POR_OMISSAO, 1, 65_535)
    intervalo = _inteiro(ambiente, VAR_INTERVALO, INTERVALO_POR_OMISSAO_S, 1, 86_400)
    copias = _inteiro(ambiente, VAR_COPIAS, None, 1, 3_650)
    armazenamento = ler_config(ambiente=nome_do_ambiente, env=ambiente)
    return Configuracao(nome_do_ambiente, porta, intervalo, copias, armazenamento)


def chave_do_certificado(valor: str) -> tuple[str, bytes]:
    """`(kid, chave)` do valor do cofre, ou `ChaveDoCertificadoInvalida`."""
    separado = separar_kid(valor)
    if separado is None:
        raise ChaveDoCertificadoInvalida()
    kid, chave = separado
    return kid, base64.b64decode(chave)


def montar_portas(
    config: Configuracao,
    segredos: Any,
    armazenamento: StorageProvider,
    *,
    entregar: EntregarAoTitular = entrega_sem_adaptador,
    apagar_contactos: ApagarContactos | None = None,
    fonte_do_catalogo: FonteDoCatalogo | None = None,
) -> PortasDosDados:
    """As portas das tres fases. A chave le-se uma vez, no arranque, e valida-se ja."""
    # O literal, e nao a constante: o `secrets_inventory` le-o do codigo.
    kid, chave = chave_do_certificado(segredos.get("offboarding_certificate_key"))
    return PortasDosDados(
        armazenamento=armazenamento,
        chave_do_certificado=chave,
        kid_do_certificado=kid,
        copias_expiram_em_dias=config.copias_dias,
        entregar=entregar,
        apagar_contactos=apagar_contactos,
        fonte_do_catalogo=fonte_do_catalogo,
        # O prazo do CGT continua NAO VERIFICADO: sem ele, nada fiscal se apaga.
        anos_fiscais=None,
    )


def ligador(ambiente: Mapping[str, str], papel: str, var_senha: str) -> Callable[[], Any]:
    """Uma fabrica de ligacoes do `pg8000` (a imagem do AGR traz-o), com o papel."""

    def ligar() -> Any:
        import pg8000.dbapi

        porta = ambiente.get(VAR_PORTA_DA_BASE, "5432")
        if not porta.isdigit():
            raise ConfiguracaoEmFalta(f"{VAR_PORTA_DA_BASE} tem de ser um numero de porta")
        ligacao = pg8000.dbapi.connect(
            user=papel,
            password=_exigir(ambiente, var_senha),
            host=ambiente.get(VAR_HOST, "127.0.0.1"),
            port=int(porta),
            database=_exigir(ambiente, VAR_BASE),
            application_name=f"kamba-{SERVICO}",
        )
        ligacao.autocommit = False
        return ligacao

    return ligar


def ligadores(ambiente: Mapping[str, str]) -> tuple[Callable[[], Any], Callable[[], Any]]:
    """`(abrir_batch, abrir_app)`, pela ordem dos argumentos do `correr_volta`."""
    return (
        ligador(ambiente, PAPEL_DO_LOTE, VAR_SENHA_BATCH),
        ligador(ambiente, PAPEL_DA_APP, VAR_SENHA_APP),
    )


def ligador_do_cofre(ambiente: Mapping[str, str]) -> Callable[[], Any]:
    """A fabrica do `kamba_identity`, para o `cofre.apagar_contactos_pelo_cofre`."""
    return ligador(ambiente, PAPEL_DO_COFRE, VAR_SENHA_COFRE)


def portas_de_producao(
    config: Configuracao,
    segredos: Any,
    armazenamento: StorageProvider,
    ambiente: Mapping[str, str],
) -> PortasDosDados:
    """As portas que o processo monta: as de `montar_portas`, com os contactos pelo cofre.

    Aqui, e nao no `__main__.py` (fora do *gate* 4), para que um ensaio veja que o
    `apagar_contactos` vai e que abre com o papel do cofre (achado 6 da revisao
    adversarial: tirar o argumento do `__main__` deixava todos os ensaios verdes).
    """
    return montar_portas(
        config, segredos, armazenamento,
        apagar_contactos=apagar_contactos_pelo_cofre(ligador_do_cofre(ambiente)),
    )


def desfecho(r: ResultadoDaVolta) -> tuple[str, str | None]:
    """O `outcome` e o `error_code` de uma volta: as fases que falharam, pelo nome."""
    if not r.falhas:
        return "offboarding_dados_volta_concluida", None
    return "offboarding_dados_volta_com_falhas", ",".join(r.falhas)


class Ciclo:
    """A volta de `intervalo_s` em `intervalo_s` segundos ate `parar`."""

    def __init__(
        self,
        abrir_batch: Callable[[], Any],
        abrir_app: Callable[[], Any],
        portas: PortasDosDados,
        relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._abrir_batch = abrir_batch
        self._abrir_app = abrir_app
        self._portas = portas
        self._relogio = relogio

    def volta(self) -> ResultadoDaVolta:
        return correr_volta(self._abrir_batch, self._abrir_app, self._portas, self._relogio())

    def correr(
        self,
        parar: threading.Event,
        intervalo_s: float,
        ao_terminar: Callable[[ResultadoDaVolta], None],
        ao_falhar: Callable[[BaseException], None],
    ) -> None:
        """Uma volta que levanta (nao devia: o `correr_volta` apanha) nao mata o ciclo."""
        while not parar.is_set():
            try:
                ao_terminar(self.volta())
            except Exception as erro:  # noqa: BLE001 — o ciclo nao morre
                ao_falhar(erro)
            parar.wait(intervalo_s)


def servidor(porta: int, ambiente: Mapping[str, str], anfitriao: str = "127.0.0.1") -> ThreadingHTTPServer:
    """So o `/healthz`. As metricas das sete fases sao do `onboarding-lote` (KAM-210)."""

    class Tratador(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — nome da biblioteca padrao
            if self.path != "/healthz":
                self.send_response(404)
                self.end_headers()
                return
            dados = json.dumps(healthz(SERVICO, VERSAO, dict(ambiente))).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def log_message(self, *_args: Any) -> None:  # o pedido nao vai a registo
            return

    servidor_http = ThreadingHTTPServer((anfitriao, porta), Tratador)
    servidor_http.daemon_threads = True
    return servidor_http


__all__ = [
    "AMBIENTES",
    "ChaveDoCertificadoInvalida",
    "Ciclo",
    "Configuracao",
    "ConfiguracaoEmFalta",
    "PORTA_POR_OMISSAO",
    "SEGREDOS_OBRIGATORIOS",
    "SEGREDO_DO_CERTIFICADO",
    "SERVICO",
    "VAR_COPIAS",
    "chave_do_certificado",
    "desfecho",
    "ler_configuracao",
    "ligador_do_cofre",
    "ligadores",
    "montar_portas",
    "portas_de_producao",
    "servidor",
]
