"""Cria os papeis de base de dados. E o unico passo que corre como admin.

    python db/bootstrap.py

Os papeis sao globais a instancia e tem de existir **antes** das migracoes: o
Alembic corre como `kamba_migrator`, e um papel nao se pode criar a si proprio.
Por isso isto nao e uma revisao do Alembic, e por isso o `downgrade base` nao os
remove — o criterio de aceitacao do KAM-003 mede objectos em `platform`, e um
papel nao vive em schema nenhum.

Idempotente: correr duas vezes deixa o mesmo estado. E **repoe**, a cada
execucao, o que alguem possa ter alterado a mao — dito por extenso, porque a
primeira versao deste ficheiro prometia isto e so fazia a primeira linha:

    atributos          `ALTER ROLE ... BYPASSRLS` num `kamba_app` e desfeito
    pertencas          `GRANT kamba_batch TO kamba_app` punha a aplicacao a um
                       `SET ROLE` de contornar a RLS; todas as pertencas dos
                       papeis, nos dois sentidos, sao revogadas
    configuracao       `ALTER ROLE ... SET search_path` e apagado (`RESET ALL`)
    palavra-passe      e **sempre** redefinida para a do ambiente, e a saida
                       di-lo

**Os papeis sao globais a instancia.** Correr isto contra uma instancia que
outros servicos usam troca-lhes as palavras-passe. O trinco `*_gate8` protege
uma base, nao protege a instancia: o gate 8 so e seguro contra uma instancia
descartavel, e `gate8.py` recusa o modo `--bd-existente` sem as tres
palavras-passe dadas explicitamente.

A palavra-passe **nunca vai em claro para o servidor**: calcula-se o
verificador SCRAM-SHA-256 deste lado e envia-se esse. Com `log_statement=ddl`,
um `ALTER ROLE ... PASSWORD '<valor>'` ficava escrito no registo do servidor.

O que cada papel pode, e a razao:

    kamba_migrator  CREATE na base (para criar o schema `platform`) e CREATE no
                    schema `public` (so para a tabela `alembic_version`, que nao
                    pode viver em `platform`: o `downgrade base` apaga o schema,
                    e o Alembic precisa de escrever a versao **depois** disso).
    kamba_app       CONNECT nesta base, e mais nada aqui. O que pode ler e
                    escrever e concedido tabela a tabela pelas migracoes.
                    (O `PUBLIC` perde `TEMPORARY` e `CONNECT` nesta base; nas
                    bases `postgres` e `template1` este ficheiro nao toca.)
    kamba_batch     CONNECT e `BYPASSRLS`. Idem.
    kamba_resolver  CONNECT. Le so as colunas que a revisao 0002 lhe concede,
                    por uma politica propria; nao contorna a RLS.
    kamba_identity  CONNECT. O unico que le `contact_endpoints` e
                    `contact_deks` (revisao 0003); nao contorna a RLS — o
                    modulo de identidade trabalha um tenant de cada vez.

Nenhum e superutilizador, nenhum cria bases nem papeis.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sys

import ligacao

#: Atributos de cada papel. Lista fechada: os nomes sao constantes deste
#: ficheiro, nunca entrada de fora, e e por isso que podem ser interpolados.
ATRIBUTOS = {
    "kamba_migrator": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
    "kamba_app": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
    "kamba_batch": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS",
    "kamba_resolver": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
    "kamba_identity": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
}


def _executar_formatado(cursor, modelo: str, *argumentos: str) -> None:
    """Executa SQL de utilidade com identificadores e literais citados pelo servidor.

    `ALTER ROLE ... PASSWORD` e `GRANT ... ON DATABASE` nao aceitam parametros
    ligados. Em vez de citar a mao, pede-se ao servidor que construa a instrucao
    com `format()` (`%I` identificador, `%L` literal) e executa-se o resultado.
    A palavra-passe nunca passa por concatenacao de cadeias deste lado.
    """
    marcadores = ", ".join(["%s::text"] * len(argumentos))
    cursor.execute(f"SELECT format(%s, {marcadores})", (modelo, *argumentos))
    cursor.execute(cursor.fetchone()[0])


ITERACOES_SCRAM = 4096


def verificador_scram(senha: str, sal: bytes | None = None) -> str:
    """O verificador SCRAM-SHA-256 de uma palavra-passe (RFC 5802, formato do PostgreSQL).

    O servidor guarda isto e nao a palavra-passe; quando o `ALTER ROLE` recebe
    uma cadeia com esta forma, guarda-a tal como vem. Assim a palavra-passe em
    claro nunca sai deste processo.

    So ASCII: o SCRAM manda normalizar com SASLprep antes de derivar a chave, e
    implementa-lo a meias dava um verificador que nao bate com o que o cliente
    calcula no login. Uma palavra-passe nao-ASCII e recusada em vez de mal
    derivada.
    """
    if not senha.isascii():
        raise ligacao.ConfiguracaoEmFalta(
            "as palavras-passe dos papeis tem de ser ASCII (o verificador SCRAM "
            "exige SASLprep para o resto, que este ficheiro nao implementa)"
        )
    sal = os.urandom(16) if sal is None else sal
    chave = hashlib.pbkdf2_hmac("sha256", senha.encode("ascii"), sal, ITERACOES_SCRAM)
    chave_cliente = hmac.new(chave, b"Client Key", hashlib.sha256).digest()
    chave_guardada = hashlib.sha256(chave_cliente).digest()
    chave_servidor = hmac.new(chave, b"Server Key", hashlib.sha256).digest()
    b64 = lambda dados: base64.b64encode(dados).decode("ascii")  # noqa: E731
    return (
        f"SCRAM-SHA-256${ITERACOES_SCRAM}:{b64(sal)}"
        f"${b64(chave_guardada)}:{b64(chave_servidor)}"
    )


def _revogar_pertencas(cursor, feito: list[str]) -> None:
    """Nenhum dos papeis pertence a outro papel, nem tem membros."""
    papeis = list(ATRIBUTOS)
    cursor.execute(
        "SELECT g.rolname, m.rolname FROM pg_auth_members a "
        "JOIN pg_roles g ON g.oid = a.roleid JOIN pg_roles m ON m.oid = a.member "
        "WHERE g.rolname = ANY(%s) OR m.rolname = ANY(%s)",
        (papeis, papeis),
    )
    for grupo, membro in cursor.fetchall():
        _executar_formatado(cursor, "REVOKE %I FROM %I", grupo, membro)
        feito.append(f"pertenca revogada: {membro} deixou de pertencer a {grupo}")


def aplicar(ambiente=None) -> list[str]:
    """Cria ou repoe os papeis. Devolve o que fez, sem segredos."""
    feito: list[str] = []
    base = ligacao.alvo(ambiente).base
    senhas = {
        papel: ligacao.credenciais(identidade, ambiente)[1]
        for identidade, papel in ligacao.PAPEIS.items()
    }

    conexao = ligacao.ligar("admin", ambiente)
    conexao.autocommit = True
    try:
        cursor = conexao.cursor()
        for papel, atributos in ATRIBUTOS.items():
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (papel,))
            if cursor.fetchone() is None:
                cursor.execute(f"CREATE ROLE {papel} {atributos}")
                feito.append(f"papel {papel} criado")
            else:
                cursor.execute(f"ALTER ROLE {papel} {atributos}")
                feito.append(f"papel {papel} ja existia; atributos repostos")
            cursor.execute(f"ALTER ROLE {papel} RESET ALL")
            _executar_formatado(
                cursor,
                "ALTER ROLE %I PASSWORD %L",
                papel,
                verificador_scram(senhas[papel]),
            )
            feito.append(f"papel {papel}: palavra-passe redefinida para a do ambiente")
            _executar_formatado(cursor, "GRANT CONNECT ON DATABASE %I TO %I", base, papel)

        _revogar_pertencas(cursor, feito)

        # O `PUBLIC` tem, por omissao, `CONNECT` e `TEMPORARY` em cada base. Com
        # `TEMPORARY`, `CREATE TEMP TABLE` sob `kamba_app` sucede — e o criterio
        # de aceitacao diz que `CREATE TABLE` sob `kamba_app` falha, sem
        # excepcao para as temporarias.
        _executar_formatado(
            cursor, "REVOKE TEMPORARY, CONNECT ON DATABASE %I FROM PUBLIC", base
        )

        # Desde o PostgreSQL 15 o PUBLIC ja nao tem CREATE em `public`. Diz-se
        # na mesma: a propriedade «kamba_app nao cria tabelas» nao pode depender
        # de uma omissao da versao.
        cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        _executar_formatado(
            cursor, "GRANT CREATE ON DATABASE %I TO %I", base, "kamba_migrator"
        )
        cursor.execute("GRANT USAGE, CREATE ON SCHEMA public TO kamba_migrator")
        feito.append(f"privilegios de base concedidos em {base}")
    finally:
        conexao.close()
    return feito


def main() -> int:
    try:
        for linha in aplicar():
            print(f"bootstrap: {linha}")
    except ligacao.ConfiguracaoEmFalta as erro:
        print(f"bootstrap: {erro}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
