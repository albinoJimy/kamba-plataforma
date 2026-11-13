"""O lexico, o vocabulario e a versao, lidos da base (KAM-062, §4.4 e §5.3).

A normalizacao (`kamba_core.idx.normalizacao`) e pura; este modulo e quem lhe
da as entradas, dentro da transaccao do chamador e **com o contexto de tenant
dele**. Nao ha parametro de tenant em nenhuma consulta daqui: a RLS do
`idx.termo_canonico` deixa ler as entradas globais e as do tenant do contexto, e
a do `idx.search_doc` so as do tenant do contexto.

## A versao, e o que ela diz

O `idx.norm_versao` (revisao `0049`) e um registo so de acrescento: cada
escrita no `idx.termo_canonico` acrescenta uma linha, por gatilho, e diz se
afecta o indice (marca ou unidade) ou so a consulta. Daqui saem dois numeros:

* **`versao`** — a maior de todas. E a `norm_versao` que a consulta devolve, a
  que um documento reindexado grava e a chave do *cache*;
* **`versao_do_indice`** — a maior das que afectam o indice. Um documento com
  `norm_versao` abaixo dela esta desactualizado e o *worker* reindexa-o.

Alterar um sinonimo sobe a primeira e nao a segunda: nenhum documento fica
marcado (criterio 4). Sem linhas, as duas sao **1**, que e a versao com que o
KAM-061 escreveu o indice.

## O vocabulario (§5.3), e a adaptacao

O §5.3 obtem o vocabulario por `ts_stat` sobre o `fts`. O `fts` guarda
**radicais** (`portuguese_stem`), e um *typo* compara-se mal com um radical:
«frigorifico» fica `frigorif`, e a semelhanca de «frigorifco» com ele cai.
Aqui o vocabulario sao as **palavras** dos documentos visiveis do tenant — o
mesmo texto que gera o `fts`, antes do radical —, menos as palavras vazias da
configuracao `idx.kamba_pt` (as que o `fts` descarta). Por isso uma palavra do
vocabulario e uma palavra que o ramo `fts` encontra num documento visivel, e
com o `or` do `q_or` a pergunta corrigida inteira tambem: o «>= 1 candidato
apos correccao» do criterio 5 (a fronteira esta no `normalizacao`).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from .normalizacao import Lexico, Vocabulario

#: As linhas activas do lexico que o contexto deixa ler (globais e do tenant).
SQL_LER_LEXICO: Final = """
  SELECT tenant_id::text AS tenant_id, tipo, termo, canonico, peso
    FROM idx.termo_canonico
   WHERE activo
   ORDER BY id
"""

#: As duas versoes. Sem linhas, 1 e 1: a versao do KAM-061.
SQL_LER_VERSOES: Final = """
  SELECT COALESCE(max(versao), 1) AS versao,
         COALESCE(max(versao) FILTER (WHERE afecta_indice), 1) AS versao_do_indice
    FROM idx.norm_versao
"""

#: As palavras dos documentos visiveis do tenant do contexto, com a frequencia.
#: Junta `platform.tenants` com `estado = 'ativo'` pela mesma razao da porta
#: `tn` do `idx.candidatos`: um vocabulo de um tenant fechado nao da candidato.
SQL_LER_VOCABULARIO: Final = """
  SELECT w.palavra, count(*)::int AS frequencia
    FROM idx.search_doc d
    JOIN platform.tenants t ON t.id = d.tenant_id AND t.estado = 'ativo'
   CROSS JOIN LATERAL regexp_split_to_table(
           d.nome_norm || ' ' || COALESCE(d.marca_canon, '') || ' '
           || COALESCE(d.categoria_canon, '') || ' ' || d.descr_norm, '\\s+') AS w(palavra)
   WHERE d.visivel
     AND d.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
     AND w.palavra <> ''
     AND to_tsvector('idx.kamba_pt'::regconfig, w.palavra) <> ''::tsvector
   GROUP BY w.palavra
"""


@dataclass(frozen=True)
class Versoes:
    """As duas versoes do `idx.norm_versao` (ver a nota do modulo)."""

    versao: int
    versao_do_indice: int


def consultar(bd: Any, sql: str, parametros: tuple[object, ...] = ()) -> list[dict[str, Any]]:
    """As linhas de uma leitura, por um `ClienteSql` (KAM-006) ou por um cursor.

    O consumidor de eventos fala por `executar(...).linhas`; a camada de
    resposta, pelo cursor do `tenant_guard.tx`. A leitura e a mesma.
    """
    if hasattr(bd, "executar"):
        return [dict(linha) for linha in bd.executar(sql, parametros).linhas]
    bd.execute(sql, parametros)
    linhas = bd.fetchall()
    nomes = [coluna[0] for coluna in bd.description]
    return [
        dict(linha) if isinstance(linha, dict) else dict(zip(nomes, linha, strict=True))
        for linha in linhas
    ]


def ler_versoes(bd: Any) -> Versoes:
    """As duas versoes, na transaccao do chamador."""
    linha = consultar(bd, SQL_LER_VERSOES)[0]
    return Versoes(int(linha["versao"]), int(linha["versao_do_indice"]))


def ler_lexico(bd: Any, tenant_id: object, versao: int) -> Lexico:
    """O lexico do tenant do contexto, ja com a precedencia aplicada."""
    return Lexico.de_linhas(consultar(bd, SQL_LER_LEXICO), tenant_id, norm_versao=versao)


def ler_vocabulario(bd: Any) -> Vocabulario:
    """O vocabulario do tenant do contexto (§5.3, com a adaptacao da nota)."""
    linhas = consultar(bd, SQL_LER_VOCABULARIO)
    return Vocabulario.de_frequencias({str(l["palavra"]): int(l["frequencia"]) for l in linhas})


#: O TTL do *cache*, em segundos. **Proposta**: o vocabulario muda com o
#: catalogo e nao com a versao, e 60 s e o atraso com que um produto novo passa
#: a corrigir *typos*. O lexico e invalidado pela versao, nao pelo TTL.
TTL_DO_CACHE_S: Final = 60.0

#: Quantos tenants o *cache* guarda. **Proposta**: o Piloto tem dezenas.
MAXIMO_DE_TENANTS_NO_CACHE: Final = 256


@dataclass
class _Entrada:
    versao: int
    lexico: Lexico
    vocabulario: Vocabulario
    lido_em: float


class Cache:
    """Lexico e vocabulario por tenant, com TTL e invalidados pela versao.

    Cada leitura paga **uma** consulta (as versoes); o lexico e o vocabulario so
    se releem quando a versao muda ou o TTL passa. O relogio entra por
    parametro, para o ensaio o controlar.
    """

    def __init__(
        self,
        ttl_s: float = TTL_DO_CACHE_S,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._relogio = relogio
        self._por_tenant: dict[str, _Entrada] = {}

    def entradas(self, cursor: Any, tenant_id: object) -> tuple[Lexico, Vocabulario]:
        """O lexico e o vocabulario do tenant, do *cache* ou da base."""
        chave = str(tenant_id)
        versao = ler_versoes(cursor).versao
        agora = self._relogio()
        entrada = self._por_tenant.get(chave)
        if entrada is None or entrada.versao != versao or agora - entrada.lido_em > self._ttl_s:
            entrada = _Entrada(
                versao=versao,
                lexico=ler_lexico(cursor, tenant_id, versao),
                vocabulario=ler_vocabulario(cursor),
                lido_em=agora,
            )
            self._por_tenant.pop(chave, None)
            self._por_tenant[chave] = entrada
            # Um tecto, para o *cache* nao crescer com o numero de tenants: sai
            # o lido ha mais tempo (a ordem de insercao do `dict`).
            while len(self._por_tenant) > MAXIMO_DE_TENANTS_NO_CACHE:
                self._por_tenant.pop(next(iter(self._por_tenant)))
        return entrada.lexico, entrada.vocabulario


#: O *cache* do processo. Um por processo, e nao partilhado entre processos:
#: cada um invalida-o pela versao que le.
CACHE: Final = Cache()
