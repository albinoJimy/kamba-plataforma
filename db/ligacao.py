"""Ligacao a base da plataforma, configurada so pelo ambiente.

Seis identidades, e nenhuma se confunde com outra:

    admin      o superutilizador da instancia. So o `bootstrap.py` o usa, para
               criar os papeis. Nenhuma migracao e nenhum servico corre com ele.
    migrator   `kamba_migrator` — DDL, dono das tabelas. So as migracoes.
    app        `kamba_app` — `NOBYPASSRLS`, sem DDL. Os servicos.
    batch      `kamba_batch` — `BYPASSRLS`, auditado. Jobs nomeados.
    resolver   `kamba_resolver` — le so as colunas que resolvem
               `phone_number_id -> tenant`, antes de haver contexto (KAM-004).
    audit      `kamba_audit` — o unico que le `audit_log` (KAM-012). O
               `kamba_app` escreve e nao le.
    identity   `kamba_identity` — o unico que le `contact_endpoints` e
               `contact_deks`. So o modulo de identidade (KAM-008).

Os nomes dos papeis sao os do dicionario §3.2 (emendas 1.2, 1.5 e 1.8). Os nomes das
variaveis das palavras-passe sao os que o `EnvProvider` do KAM-010 le
(`KAMBA_SECRET_` + id do inventario em maiusculas), para que os dois tickets
falem do mesmo segredo com o mesmo nome sem que um importe o outro.

Uma variavel em falta levanta um erro que **nomeia a variavel e nunca o valor**.
"""

from __future__ import annotations

import dataclasses
import os
import urllib.parse

#: Papel de base de dados de cada identidade. `admin` nao tem nome fixo: e o
#: `POSTGRES_USER` da instancia.
#:
#: **Sete**, desde o KAM-026: os tres do KAM-003, o `kamba_resolver`
#: (KAM-004), o `kamba_identity` (KAM-008), o `kamba_audit` (KAM-012) e o
#: `kamba_agr` (KAM-026), que e o unico que nao toca no esquema `platform`.
PAPEIS = {
    "migrator": "kamba_migrator",
    "app": "kamba_app",
    "batch": "kamba_batch",
    "resolver": "kamba_resolver",
    "identity": "kamba_identity",
    "audit": "kamba_audit",
    "agr": "kamba_agr",
}

#: Variavel de ambiente da palavra-passe de cada identidade.
VARIAVEL_DA_SENHA = {
    "admin": "POSTGRES_PASSWORD",
    "migrator": "KAMBA_SECRET_DB_MIGRATOR_PASSWORD",
    "app": "KAMBA_SECRET_DB_APP_PASSWORD",
    "batch": "KAMBA_SECRET_DB_BATCH_PASSWORD",
    "resolver": "KAMBA_SECRET_DB_RESOLVER_PASSWORD",
    "identity": "KAMBA_SECRET_DB_IDENTITY_PASSWORD",
    "audit": "KAMBA_SECRET_DB_AUDIT_PASSWORD",
    "agr": "KAMBA_SECRET_DB_AGR_PASSWORD",
}


class ConfiguracaoEmFalta(RuntimeError):
    """Falta uma variavel de ambiente. A mensagem diz qual; nunca um valor."""


@dataclasses.dataclass(frozen=True)
class Alvo:
    host: str
    porta: int
    base: str


def _exigir(nome: str, ambiente) -> str:
    valor = ambiente.get(nome, "")
    if not valor:
        raise ConfiguracaoEmFalta(
            f"a variavel de ambiente {nome} nao esta definida (ou esta vazia)"
        )
    return valor


def alvo(ambiente=None) -> Alvo:
    """Onde esta a base. Sem valores por omissao para o nome da base.

    O host e a porta tem omissao (`127.0.0.1:5432`); a base **nao**: uma omissao
    `kamba_platform` punha o gate 8, que faz `downgrade base`, a um esquecimento
    de distancia da base de desenvolvimento.
    """
    ambiente = os.environ if ambiente is None else ambiente
    porta = ambiente.get("KAMBA_DB_PORT", "5432")
    if not porta.isdigit():
        raise ConfiguracaoEmFalta("KAMBA_DB_PORT tem de ser um numero de porta")
    return Alvo(
        host=ambiente.get("KAMBA_DB_HOST", "127.0.0.1"),
        porta=int(porta),
        base=_exigir("KAMBA_DB_NAME", ambiente),
    )


def credenciais(identidade: str, ambiente=None) -> tuple[str, str]:
    """(utilizador, palavra-passe) de uma identidade."""
    ambiente = os.environ if ambiente is None else ambiente
    if identidade not in VARIAVEL_DA_SENHA:
        raise ValueError(f"identidade desconhecida: {identidade!r}")
    if identidade == "admin":
        utilizador = _exigir("POSTGRES_USER", ambiente)
    else:
        utilizador = PAPEIS[identidade]
    return utilizador, _exigir(VARIAVEL_DA_SENHA[identidade], ambiente)


def ligar(identidade: str, ambiente=None):
    """Abre uma ligacao DB-API (pg8000) com a identidade pedida."""
    import pg8000.dbapi

    destino = alvo(ambiente)
    utilizador, senha = credenciais(identidade, ambiente)
    return pg8000.dbapi.connect(
        user=utilizador,
        password=senha,
        host=destino.host,
        port=destino.porta,
        database=destino.base,
        application_name=f"kamba-db:{identidade}",
    )


def url_sqlalchemy(identidade: str, ambiente=None) -> str:
    """URL para o SQLAlchemy/Alembic. Nunca se imprime: contem a palavra-passe."""
    destino = alvo(ambiente)
    utilizador, senha = credenciais(identidade, ambiente)
    return (
        "postgresql+pg8000://"
        f"{urllib.parse.quote(utilizador, safe='')}:{urllib.parse.quote(senha, safe='')}"
        f"@{destino.host}:{destino.porta}/{urllib.parse.quote(destino.base, safe='')}"
    )
