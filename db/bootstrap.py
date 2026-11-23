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
descartavel, e `gate_bd.py` recusa o modo `--bd-existente` sem as tres
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
    kamba_pay_hooks CONNECT. O papel que atende os callbacks de pagamento
                    (revisao 0029): grava no `payment_callbacks_inbox`, que nao
                    tem `tenant_id`, e resolve o `webhook_token` por funcao.
                    Nao contorna a RLS e nao le cobrancas nem o ledger.
    kamba_pay       CONNECT. O consumidor do PAY (revisao 0051): consome o
                    `order.refund_requested` e abre a `refund_cases` pela
                    porta `abrir_caso_de_reembolso`, de que e o unico com
                    `EXECUTE`. Nao contorna a RLS.

Nenhum e superutilizador, nenhum cria bases nem papeis.

E um decimo, **fora da plataforma** (KAM-247, decisao do fundador de
2026-11-23, opcao A1):

    kamba_litellm   o papel do proxy de LLM. Dono da base `kamba_litellm`, onde
                    o LiteLLM guarda as chaves virtuais e o gasto acumulado de
                    cada uma, e **sem CONNECT na base da plataforma**: nao esta
                    em `ligacao.PAPEIS`, nao recebe o `GRANT CONNECT` do ciclo
                    de baixo, e a base da plataforma ja revoga o CONNECT ao
                    PUBLIC. Na `kamba_litellm` o PUBLIC tambem o perde, e o
                    `kamba_litellm` e o unico que la entra. Dono porque as
                    migracoes do proprio LiteLLM correm no arranque dele e criam
                    as tabelas no `public` dessa base (medido no KAM-247).

So nasce quando o ambiente traz a `KAMBA_SECRET_DB_LITELLM_PASSWORD`: o proxy
corre em `staging` e `prod`, e o `dev` e os ensaios que nao o levantam nao
ganham uma base que ninguem usa. **A falta dela aqui nao e um erro, e por isso
diz-se na saida**: o compose recusa-se a arrancar o proxy sem a variavel
(`:?`), mas isso e o ambiente do contentor e nao o deste passo. Um `bootstrap`
corrido sem ela em `prod` sai com 0, e o proxy fica a falhar a autenticacao em
ciclo de reinicio. Em `staging` e `prod` corre-se com ela, antes do `litellm`
(`db/migrations/README.md`).
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
    # O papel de auditoria (KAM-012). `NOBYPASSRLS` de proposito: quem audita
    # um tenant audita **esse** tenant, e a cadeia de plataforma le-se com o
    # `kamba_batch`. E o unico com `SELECT` em `audit_log` — o `kamba_app`
    # escreve e nao le.
    "kamba_audit": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
    # O papel do checkpointer (KAM-026). `NOBYPASSRLS` como os outros, mas por
    # uma razao diferente: as tabelas do `lg` **nao tem** politica de RLS, pelo
    # que nao ha nada para contornar. O que o isola e nao ter `USAGE` no
    # `platform` — ver a nota da revisao `0020`.
    "kamba_agr": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
    # O papel estreito dos *webhooks* de pagamento (KAM-053). Existe por uma
    # razao de ordem e nao de conveniencia: resolve `webhook_token -> account`
    # **antes de existir contexto de tenant**, porque no instante em que um
    # callback chega ainda nao se sabe de quem ele e (`docs/tecnica/04` §5.1).
    #
    # `NOBYPASSRLS`, e isso parece contradizer o paragrafo acima — nao
    # contradiz. Ele nao le dado de tenant nenhum: o que alcanca e o
    # `payment_callbacks_inbox`, que **nao tem** `tenant_id`, e a resolucao do
    # *token*, que passa pela `resolve_webhook_token` e nao pela tabela. Dar-lhe
    # `BYPASSRLS` era dar-lhe tudo o mais de que ele nao precisa.
    "kamba_pay_hooks": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
    # O papel do consumidor do PAY (KAM-197, decisao (A) do fundador de
    # 2026-11-13). Existe para que a `refund_cases` tenha **um so dono**
    # imposto pela base: o COM corre como `kamba_app`, e um `EXECUTE` da porta
    # concedido ao `kamba_app` deixava o COM abrir casos. `NOBYPASSRLS`: o
    # consumo trabalha um tenant de cada vez, com o `app.tenant_id` do
    # envelope. O que pode e concedido pela revisao `0051`.
    "kamba_pay": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
}


#: O papel e a base do proxy de LLM (KAM-247). O mesmo nome nos dois, como a
#: `kamba_chatwoot` e a `kamba_medusa` do `initdb`: a base e dele e de mais
#: ninguem.
PAPEL_DO_LITELLM = "kamba_litellm"
BASE_DO_LITELLM = "kamba_litellm"
#: `KAMBA_SECRET_` + o id do inventario (`db_litellm_password`), pela regra do
#: `ligacao.py`.
VARIAVEL_DO_PAPEL_DO_LITELLM = "KAMBA_SECRET_DB_LITELLM_PASSWORD"
ATRIBUTOS_DO_LITELLM = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"


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
    papeis = [*ATRIBUTOS, PAPEL_DO_LITELLM]
    cursor.execute(
        "SELECT g.rolname, m.rolname FROM pg_auth_members a "
        "JOIN pg_roles g ON g.oid = a.roleid JOIN pg_roles m ON m.oid = a.member "
        "WHERE g.rolname = ANY(%s) OR m.rolname = ANY(%s)",
        (papeis, papeis),
    )
    for grupo, membro in cursor.fetchall():
        _executar_formatado(cursor, "REVOKE %I FROM %I", grupo, membro)
        feito.append(f"pertenca revogada: {membro} deixou de pertencer a {grupo}")


def _papel_e_base_do_litellm(cursor, senha: str, feito: list[str]) -> None:
    """O papel `kamba_litellm` e a base dele (KAM-247). Idempotente, como o resto.

    `CREATE DATABASE` nao corre numa transaccao: a ligacao do `aplicar` esta em
    `autocommit`. O dono e **reposto** a cada execucao, pela razao dos
    atributos: uma base passada a outro dono a mao deixava o proxy sem `CREATE`
    no `public` dela, e as migracoes dele falhavam no arranque seguinte.
    """
    papel, base = PAPEL_DO_LITELLM, BASE_DO_LITELLM
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (papel,))
    if cursor.fetchone() is None:
        cursor.execute(f"CREATE ROLE {papel} {ATRIBUTOS_DO_LITELLM}")
        feito.append(f"papel {papel} criado")
    else:
        cursor.execute(f"ALTER ROLE {papel} {ATRIBUTOS_DO_LITELLM}")
        feito.append(f"papel {papel} ja existia; atributos repostos")
    _executar_formatado(cursor, "ALTER ROLE %I RESET ALL", papel)
    _executar_formatado(
        cursor, "ALTER ROLE %I PASSWORD %L", papel, verificador_scram(senha)
    )
    feito.append(f"papel {papel}: palavra-passe redefinida para a do ambiente")

    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (base,))
    if cursor.fetchone() is None:
        _executar_formatado(cursor, "CREATE DATABASE %I OWNER %I", base, papel)
        feito.append(f"base {base} criada, com dono {papel}")
    else:
        _executar_formatado(cursor, "ALTER DATABASE %I OWNER TO %I", base, papel)
        feito.append(f"base {base} ja existia; dono reposto")
    # O PUBLIC tem CONNECT e TEMPORARY em cada base nova. Sem este REVOKE, os
    # papeis da plataforma entravam na base do proxy, e o dele nao precisa de
    # companhia. O dono conserva os seus privilegios: o REVOKE ao PUBLIC nao
    # lhos tira.
    #
    # **Escrito com outra ordem das palavras de proposito**: o `db/mutacoes.py`
    # muta o REVOKE da base da plataforma pelo texto, e exige que ele apareca
    # uma vez so neste ficheiro.
    _executar_formatado(
        cursor, "REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC", base
    )
    _executar_formatado(cursor, "GRANT CONNECT ON DATABASE %I TO %I", base, papel)
    feito.append(f"privilegios da base {base}: CONNECT so ao {papel}")


def _litellm_fora_da_plataforma(cursor, base: str, feito: list[str]) -> None:
    """Tira ao `kamba_litellm` o que alguem lhe tenha dado na base da plataforma.

    O bootstrap nunca lho da, e a base da plataforma ja revoga o CONNECT ao
    PUBLIC; mas um `GRANT CONNECT ... TO kamba_litellm` feito a mao punha o
    proxy dentro da plataforma, e nenhuma execucao o desfazia. Repoe-se, como os
    atributos e as pertencas (achado da revisao adversarial do KAM-247).
    """
    _executar_formatado(
        cursor, "REVOKE ALL ON DATABASE %I FROM %I", base, PAPEL_DO_LITELLM
    )
    feito.append(f"papel {PAPEL_DO_LITELLM}: nada na base {base}")


def aplicar(ambiente=None) -> list[str]:
    """Cria ou repoe os papeis. Devolve o que fez, sem segredos."""
    feito: list[str] = []
    base = ligacao.alvo(ambiente).base
    senhas = {
        papel: ligacao.credenciais(identidade, ambiente)[1]
        for identidade, papel in ligacao.PAPEIS.items()
    }
    fonte = os.environ if ambiente is None else ambiente
    senha_do_litellm = fonte.get(VARIAVEL_DO_PAPEL_DO_LITELLM, "")
    if base == BASE_DO_LITELLM:
        # A base da plataforma com o nome da do proxy dava ao papel do proxy o
        # dono da base da plataforma. Recusa-se antes de tocar em nada.
        raise ligacao.ConfiguracaoEmFalta(
            f"KAMBA_DB_NAME nao pode ser {BASE_DO_LITELLM}: e a base do proxy de LLM"
        )

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

        if senha_do_litellm:
            _papel_e_base_do_litellm(cursor, senha_do_litellm, feito)
        else:
            # Sem a variavel nao se cria nada, e nao se apaga nada: um papel e
            # uma base que ja existam ficam como estao, e a frase di-lo.
            feito.append(
                f"papel {PAPEL_DO_LITELLM}: {VARIAVEL_DO_PAPEL_DO_LITELLM} nao "
                "definida; o papel e a base do proxy de LLM nao foram criados nem "
                "repostos. Em staging e prod o proxy precisa dos dois: corra-se "
                "com ela antes de o arrancar"
            )
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (PAPEL_DO_LITELLM,))
        if cursor.fetchone() is not None:
            _litellm_fora_da_plataforma(cursor, base, feito)

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

        # O `vector` (pgvector 0.8.7) **nao e *trusted***: medido no
        # `pg_available_extension_versions` da imagem do *gate*, `trusted = f`.
        # O `kamba_migrator` nao o consegue criar, e a revisao do indice (KAM-061)
        # precisa dele para o `halfvec`. Em desenvolvimento quem o cria e o
        # `infra/compose/postgres/initdb/01-bases-e-extensoes.sql`, como
        # administrador; aqui e este passo, pela mesma razao e com a mesma guarda.
        # A revisao repete o `CREATE EXTENSION IF NOT EXISTS`, que com a extensao
        # ja criada nao pede privilegio nenhum.
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        feito.append(f"extensao vector garantida em {base}")
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
