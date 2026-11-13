"""Uma ligacao DB-API como `ClienteSql` do `consumir` (KAM-194).

O `consumir` do KAM-006 manda `BEGIN`, `COMMIT` e `ROLLBACK` como instrucoes,
porque do lado TypeScript o cliente e um `pg` em bruto. Um condutor DB-API em
modo transaccional (`pg8000`, `psycopg`) **abre a transaccao sozinho** na
primeira instrucao, e um `BEGIN` explicito dentro dela e um aviso do servidor e
mais nada — o `COMMIT` seguinte fechava a transaccao de fora. Por isso as tres
traduzem-se na API do condutor em vez de passarem.

**Uma palavra de controlo de transaccao que nao se traduz levanta**, em vez de
passar: um `SAVEPOINT` ou um `START TRANSACTION` deixado passar punha a marca e
o efeito em transaccoes diferentes **sem dar erro** — os dois modos de falha que
o `consumo.py` nomeia por extenso.

E a regra do `LigacaoDoConsumo` do AGR (`kamba_agr/eventos/consumo.py`, KAM-038),
que ficou la: as receitas de mutacao do `db/mutacoes.py` apontam para o texto
daquele ficheiro. Esta e a do IDX, e as duas confrontam-se no
`TestParidadeDaEntrega` da *suite* do AGR.
shortcut: duas copias do adaptador, presas por um ensaio de paridade; revê-se quando o AGR passar a importar daqui.
"""

from __future__ import annotations

from typing import Any, Final

from .consumo import Resultado

#: As tres que se traduzem.
TRADUZIDAS: Final = ("BEGIN", "COMMIT", "ROLLBACK")

#: As que, se aparecerem, significam que o contrato do `consumir` mudou.
PROIBIDAS: Final = ("START", "END", "SAVEPOINT", "RELEASE", "ABORT")


class ClienteDaLigacao:
    """Adapta uma ligacao DB-API transaccional ao `ClienteSql` do KAM-006."""

    __slots__ = ("_ligacao",)

    def __init__(self, ligacao: Any) -> None:
        self._ligacao = ligacao

    def executar(self, sql: str, parametros: tuple[object, ...] = ()) -> Resultado:
        primeira = sql.strip().split(maxsplit=1)[0].upper() if sql.strip() else ""
        if primeira in TRADUZIDAS:
            if primeira == "COMMIT":
                self._ligacao.commit()
            elif primeira == "ROLLBACK":
                self._ligacao.rollback()
            # O `BEGIN` nao faz nada: o condutor abre a transaccao na instrucao
            # seguinte, que e o `set_config` do contexto.
            return Resultado()
        if primeira in PROIBIDAS:
            raise RuntimeError(
                f"instrucao de transaccao nao traduzida: {primeira}. Deixa-la passar "
                "punha a marca e o efeito em transaccoes diferentes sem dar erro"
            )
        cursor = self._ligacao.cursor()
        try:
            cursor.execute(sql, parametros)
            if cursor.description is None:
                return Resultado(contagem=cursor.rowcount)
            colunas = [coluna[0] for coluna in cursor.description]
            linhas = [
                {
                    (nome.decode() if isinstance(nome, bytes) else str(nome)): valor
                    for nome, valor in zip(colunas, linha, strict=True)
                }
                for linha in cursor.fetchall()
            ]
            return Resultado(linhas=linhas, contagem=cursor.rowcount)
        finally:
            cursor.close()
