"""A linha de `dat.llm_call_log`: uma por chamada, sem conteudo (KAM-030).

E o espelho do `tls/auditoria.py` para o gateway, e a forma e deliberadamente a
mesma — `COLUNAS`, `confirmar`, `escrever` — porque quem leu uma le a outra. As
diferencas sao tres, e as tres tem razao:

1. **O esquema e `dat` e nao `platform`.** E analitica, nao estado de negocio
   (revisao `0023`).
2. **Falhar a escrever nao falha a chamada.** Na ToolLayer uma falha de registo
   **levanta**, porque o efeito de uma *tool* `money` ja aconteceu e repetir sem
   registo e pior. Aqui o efeito que ja aconteceu e **a transferencia**, e nao se
   desfaz: levantar fazia o turno falhar e o *job* voltar a fila, que **repetia a
   chamada ao modelo** — segunda transferencia, segundo custo, e o mesmo registo
   a falhar. Por isso esta funcao **nao levanta**: conta na metrica
   `agr_llm_registo_falhou_total` e devolve a resposta ao grafo. A perda e uma
   linha de registo; a alternativa era pagar duas chamadas e perder as duas.
   Ver a `confirmar`, abaixo, que e o que retira a causa provavel disto.
3. **Nao ha `args_hash` nem `args_redacted`.** Nao ha nada da chamada para
   resumir: o *prompt* nao entra, nem em *hash*. Um *hash* do *prompt* era um
   identificador estavel de um texto de cliente — o `docs/tecnica/08` §7.3
   proibe-o, e o ADR-010 diz que logs nao levam conteudo. A minimizacao de PII
   antes do modelo e o KAM-112, que este ticket desbloqueia.

## O que a linha **nao** guarda, e como isso se prova

Nenhuma das dezesseis colunas pode levar *prompt*, resposta, telefone ou texto
de cliente. Mas isso nao se prova a ler o DDL nem este ficheiro: prova-se por
varrimento dos dados com canarios, em `db/tests_agr/test_llm_call_log.py`. E a
licao do KAM-026 — o varrimento de privacidade dele dava zero por procurar texto
num campo `msgpack`, e o critero passava pela razao errada.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Any, Final

from kamba_core import tenant_guard

#: As catorze colunas que quem chama escreve, pela ordem do `INSERT`. **E a
#: mesma lista do `COLUNAS_DO_CHAMADOR` da revisao `0023`**, e um teste
#: confronta as duas: se divergirem, o `INSERT` rebenta por privilegio e nao em
#: silencio.
COLUNAS: Final = (
    "tenant_id",
    "trace_id",
    "vertical",
    "no_grafo",
    "papel",
    "graph_version",
    "modelo",
    "fornecedor",
    "tokens_in",
    "tokens_out",
    "tokens_cache",
    "custo_usd",
    "latencia_ms",
    "resultado",
)

TABELA: Final = "dat.llm_call_log"

SQL_ESCREVER: Final = (
    f"INSERT INTO {TABELA} (" + ", ".join(COLUNAS) + ") VALUES ("
    + ", ".join(["%s"] * len(COLUNAS))
    + ")"
)

#: A guarda de arranque, **por coluna** e nao por tabela: o `GRANT` da revisao
#: `0023` e por coluna, e um `has_table_privilege(..., 'INSERT')` devolve falso
#: com privilegios de coluna concedidos. E a mesma razao escrita no
#: `tls/auditoria.py`.
SQL_CONFIRMAR: Final = "SELECT " + ", ".join(
    f"has_column_privilege('{TABELA}', '{coluna}', 'INSERT')" for coluna in COLUNAS
)


class RegistoIndisponivelError(RuntimeError):
    """Nao se conseguiu confirmar a `dat.llm_call_log` no arranque.

    **So no arranque.** Em execucao nao se levanta — ver o ponto 2 da nota do
    modulo.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class LinhaDeChamada:
    """Uma linha de `dat.llm_call_log`, montada e ainda nao escrita."""

    tenant_id: str
    trace_id: str
    papel: str
    modelo: str
    fornecedor: str
    resultado: str
    vertical: str | None = None
    no_grafo: str | None = None
    graph_version: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cache: int | None = None
    custo_usd: Decimal | None = None
    latencia_ms: int | None = None

    def parametros(self) -> tuple[Any, ...]:
        """Os catorze valores, pela ordem de `COLUNAS`."""
        return (
            self.tenant_id,
            self.trace_id,
            self.vertical,
            self.no_grafo,
            self.papel,
            self.graph_version,
            self.modelo,
            self.fornecedor,
            self.tokens_in,
            self.tokens_out,
            self.tokens_cache,
            self.custo_usd,
            self.latencia_ms,
            self.resultado,
        )


def confirmar(ligacao: Any) -> None:
    """Confirma que esta ligacao escreve a tabela. Levanta se nao.

    Corre no arranque (codigo de saida **7**) e **nao escreve nada**: a tabela e
    *append-only* e uma linha de ensaio ficava la para sempre, a contar numa
    tabela de custo. E a mesma escolha do `tls/auditoria.confirmar`.

    Isto e o que torna defensavel o ponto 2 da nota do modulo: a causa de longe
    mais provavel de uma escrita falhar e **configuracao** — privilegio em falta,
    esquema na revisao errada —, e essa descobre-se aqui, antes de haver chamadas
    para registar. O que fica por cobrir e a base cair a meio de um turno, e para
    isso a escolha certa e nao repetir a chamada.
    """
    cursor = ligacao.cursor()
    try:
        cursor.execute(SQL_CONFIRMAR)
        linha = cursor.fetchone()
        ligacao.commit()
    except Exception as erro:  # noqa: BLE001 — a razao vai na mensagem
        ligacao.rollback()
        raise RegistoIndisponivelError(
            f"nao se conseguiu confirmar a `{TABELA}`: {erro}"
        ) from erro
    finally:
        cursor.close()
    sem_privilegio = [
        coluna for coluna, permitido in zip(COLUNAS, linha, strict=True) if not permitido
    ]
    if sem_privilegio:
        raise RegistoIndisponivelError(
            f"o papel desta ligacao nao tem `INSERT` em {sem_privilegio} de "
            f"`{TABELA}`; chamadas a um modelo corriam sem registo de custo nem de "
            "transferencia (ADR-008, ADR-018)"
        )


def escrever(ligacao: Any, linha: LinhaDeChamada) -> bool:
    """Escreve a linha sob o contexto de tenant. **Nao levanta**; devolve se escreveu.

    Chama-se `escrever` e nao `registar`: o `log_policy` do *gate* 2 proibe
    `.registar(...)` no codigo de servico, porque e a porta sem tipos do
    *logger*. A mesma razao escrita no `tls/auditoria.py`.

    O `tenant_guard.tx` poe o `app.tenant_id` do contexto, e e o `WITH CHECK` da
    politica `tenant_iso` que impede uma linha de custo no nome de outro tenant.
    """
    try:
        with tenant_guard.tx(ligacao, linha.tenant_id) as cursor:
            cursor.execute(SQL_ESCREVER, linha.parametros())
    except Exception:  # noqa: BLE001 — ver o ponto 2 da nota do modulo
        return False
    return True
