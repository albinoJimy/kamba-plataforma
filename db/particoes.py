"""As particoes mensais de `platform.events_log` e `dat.llm_call_log` (KAM-071).

E o `db/eventos_particoes.py` que o `docs/eventos.md` §7 dava por fazer, com um
nome que cobre as duas tabelas: cria a particao de um mes e larga a de um mes
vencido. Quem decide **quais** e o *job* (`kamba_core.retencao.jobs`), como
`kamba_batch`; isto e so a mao que faz o DDL.

## Porque e que corre com a ligacao do dono

`CREATE TABLE ... PARTITION OF` e `DROP TABLE` de uma particao exigem ser dono
do pai, e o dono e o `kamba_migrator`. As duas alternativas foram pesadas e
recusadas:

* **uma funcao `SECURITY DEFINER`** que o `kamba_batch` chamasse: e DDL dinamico
  dentro de `$$`, que o *gate* 3b recusa por desenho
  (`tools/canon_lint/sql.py` — «uma funcao que cria tabelas ... nao pode criar
  nada»). Ensinar-lhe essa forma era afrouxar um *gate*;
* **dar ao `kamba_batch` a posse das tabelas**: com ela vinham `ALTER`, `DROP`
  do pai e `DISABLE TRIGGER` — e o `kamba_batch` e o papel que contorna a RLS.

## O que este modulo defende, mesmo com a ligacao mais forte

* **Duas tabelas, por lista fechada.** O nome da particao e derivado do mes, e
  nunca recebido.
* **Largar so o que passou o prazo, pelo relogio da base.** O prazo e o da
  politica do `kamba_core.retencao` — importado, e nao repetido: duas
  constantes com o mesmo significado em dois sitios divergem sem nenhum portao
  o ver (a licao do KAM-070).
* **Nao le linhas, e nao decide o hold.** O dono esta sujeito ao `FORCE` e veria
  zero; o hold verifica-o o *job* como `kamba_batch` antes de chamar aqui.
* **A particao nova nasce com RLS `ENABLE` + `FORCE` e a politica `tenant_iso`**
  do `db/rls.py` (o mesmo predicado, importado), e sem privilegio nenhum: quem
  le, le pelo pai. E o que o `verificar_particoes` do X-05 exige — a RLS do pai
  nao cobre quem le a particao directamente (medido no KAM-005).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_NUCLEO = str(Path(__file__).resolve().parents[1] / "libs" / "py-core" / "src")
if _NUCLEO not in sys.path:
    sys.path.insert(0, _NUCLEO)

from kamba_core.retencao import politica  # noqa: E402

import rls  # noqa: E402

#: tabela -> (esquema, pai, classe da politica).
ALVOS = {
    "platform.events_log": ("platform", "events_log", "events_log"),
    "dat.llm_call_log": ("dat", "llm_call_log", "llm_call_log"),
}


class ParticaoRecusada(ValueError):
    """A tabela nao e de particoes mensais, ou o mes nao se pode largar."""


def _alvo(tabela: str) -> tuple[str, str, str]:
    try:
        return ALVOS[tabela]
    except KeyError:
        raise ParticaoRecusada(f"{tabela} nao tem particoes mensais") from None


def _limites(mes: date) -> tuple[datetime, datetime]:
    if mes.day != 1:
        raise ParticaoRecusada("o mes de uma particao e o primeiro dia do mes")
    desde = datetime(mes.year, mes.month, 1, tzinfo=timezone.utc)
    ano, m = (mes.year + 1, 1) if mes.month == 12 else (mes.year, mes.month + 1)
    return desde, datetime(ano, m, 1, tzinfo=timezone.utc)


def nome_da_particao(tabela: str, mes: date) -> str:
    _, pai, _ = _alvo(tabela)
    return f"{pai}_{mes:%Y_%m}"


class GestorDeParticoes:
    """A implementacao do `jobs.Particoes`, com a ligacao do dono."""

    def __init__(self, abrir_ligacao_do_dono: Callable[[], Any]) -> None:
        self.abrir = abrir_ligacao_do_dono

    def _transaccao(self, trabalho: Callable[[Any], None]) -> None:
        ligacao = self.abrir()
        try:
            cursor = ligacao.cursor()
            try:
                trabalho(cursor)
                ligacao.commit()
            except BaseException:
                ligacao.rollback()
                raise
        finally:
            ligacao.close()

    def criar(self, tabela: str, mes: date) -> None:
        """Cria a particao do mes, com a RLS dela. Idempotente."""
        esquema, pai, _ = _alvo(tabela)
        desde, ate = _limites(mes)
        nome = nome_da_particao(tabela, mes)
        predicado = rls.predicado()

        def trabalho(cursor: Any) -> None:
            cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (f"{esquema}.{nome}",))
            if cursor.fetchone()[0]:
                return
            # Os limites sao literais: DDL nao aceita parametros, e os dois vem
            # de um `date`, nunca de texto de quem chama.
            cursor.execute(
                f"CREATE TABLE {esquema}.{nome} PARTITION OF {esquema}.{pai} "
                f"FOR VALUES FROM ('{desde.isoformat()}') TO ('{ate.isoformat()}')"
            )
            cursor.execute(f"ALTER TABLE {esquema}.{nome} ENABLE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {esquema}.{nome} FORCE ROW LEVEL SECURITY")
            cursor.execute(
                f"CREATE POLICY {rls.POLITICA} ON {esquema}.{nome} "
                f"USING ({predicado}) WITH CHECK ({predicado})"
            )

        self._transaccao(trabalho)

    def largar(self, tabela: str, mes: date) -> None:
        """Larga a particao do mes, se ja passou o prazo da politica.

        Recusa um mes cujo fim nao esteja antes de `now() - prazo` pelo relogio
        da **base**: o *job* passa o mes, e um *job* com o relogio errado (ou um
        chamador enganado) largava o mes corrente. Idempotente: uma particao
        que ja nao existe nao e erro.
        """
        esquema, pai, classe = _alvo(tabela)
        _, ate = _limites(mes)
        prazo = politica.classe(classe).prazo
        nome = nome_da_particao(tabela, mes)

        def trabalho(cursor: Any) -> None:
            cursor.execute("SELECT now()")
            agora = cursor.fetchone()[0]
            if ate > prazo.antes_de(agora):
                raise ParticaoRecusada(f"{nome} ainda esta dentro do prazo de {classe}")
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_inherits i "
                "  JOIN pg_class c ON c.oid = i.inhrelid "
                "  JOIN pg_namespace n ON n.oid = c.relnamespace "
                " WHERE n.nspname = %s AND c.relname = %s "
                "   AND i.inhparent = %s::regclass)",
                (esquema, nome, f"{esquema}.{pai}"),
            )
            if cursor.fetchone()[0]:
                cursor.execute(f"DROP TABLE {esquema}.{nome}")

        self._transaccao(trabalho)


__all__ = ["ALVOS", "GestorDeParticoes", "ParticaoRecusada", "nome_da_particao"]
