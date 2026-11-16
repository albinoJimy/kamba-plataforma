"""O `golden_search` contra um PostgreSQL real (KAM-064): instrumento, fora do CI.

    python db/golden_search.py [relatorio.json] [--sem-afinacao]

Levanta o PostgreSQL do *gate* (a mesma imagem, por *digest*, pelo
`gate_bd.com_contentor`), aplica os papeis e as migracoes ate a cabeca, semeia
os **cinco catalogos sinteticos** de `eval/search/data/catalogos/`, cada um no
seu tenant `ativo`, indexa-os pelo consumidor do IDX (`consumir_evento`, o
caminho de producao) e corre as consultas de `eval/search/data/golden_search/`
pela camada de resposta real (`kamba_core.idx.pesquisa.procurar`), como
`kamba_app`, com o tenant no contexto:

    lexical    sem `vectorial`: o `p_qvec` vai nulo
    hibrido    com o catalogo embebido pelo *worker* do KAM-063 e a pergunta
               pela `ConsultaVectorial`, os dois com o fornecedor FALSO
               (`tools/eval_search/embeddings_falsos.py`): zero chamadas pagas

Depois, dentro de `dataset.afinacao()` (que recusa ler a divisao `teste`), a
**afinacao em dev**: o limiar do `pg_trgm` varrido, e o par (pontuador, limiar)
do `retrieve` do AGR varrido sobre o `score_normalizado` real.

O relatorio JSON e o Markdown saem lado a lado (`tools/eval_search/runner.py`);
o `python -m eval_search.gate verificar` compara-o com a linha de base.

**O executor passa so o texto**, e nunca as `restricoes` anotadas: o tecto de
preco tem de sair da normalizacao do KAM-062 («ate 2000 kz»), como sai em
producao. As `restricoes` do ficheiro sao da anotacao — os graus ja excluem o
que fica acima do tecto dito.

**Porque nao e uma suite do `gate_bd.py`**, pela razao do `db/carga.py` e do
`db/desempenho_indice.py`: o `SUITES` e o que o CI corre, e por o *gate* de
qualidade a correr em CI e decisao do fundador (bloco do KAM-064, criterio 6).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

DB = Path(__file__).resolve().parent
RAIZ = DB.parent
sys.path.insert(0, str(DB))
sys.path.insert(0, str(RAIZ / "libs" / "py-core" / "src"))
sys.path.insert(0, str(RAIZ / "services" / "agr" / "src"))
sys.path.insert(0, str(RAIZ / "tools"))

import gate_bd  # noqa: E402

#: O que o preco desce depois de indexado: 1 Kz, em unidade menor.
AJUSTE_DE_PRECO_MINOR = 100

#: Os limiares do `pg_trgm` que a afinacao varre, em dev.
LIMIARES_DE_PALAVRA = (0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6)
#: Os limiares do `retrieve` do AGR, contra o `score_normalizado`.
LIMIARES_DO_RRF = (0.0, 0.1, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.7, 0.8)


class _Cliente:
    """O `ClienteSql` do KAM-006 sobre uma ligacao em `autocommit` (o do ensaio)."""

    def __init__(self, conexao) -> None:
        self.cursor = conexao.cursor()

    def executar(self, sql: str, parametros=()):
        from kamba_core.eventos.consumo import Resultado

        self.cursor.execute(sql, tuple(parametros))
        linhas = ()
        if self.cursor.description:
            nomes = [d[0] for d in self.cursor.description]
            linhas = tuple(dict(zip(nomes, linha)) for linha in self.cursor.fetchall())
        contagem = self.cursor.rowcount
        return Resultado(linhas=linhas, contagem=None if contagem < 0 else contagem)


class _PortaLocal:
    """A porta do KAM-069 para um destino que nao sai da maquina: autoriza-o a ele, e so a ele."""

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
        from eval_search import embeddings_falsos

        if fornecedor != embeddings_falsos.FORNECEDOR:
            raise PermissionError(f"destino {fornecedor!r} nao autorizado na avaliacao")


class _FornecedorFalso:
    """O `FornecedorDeEmbeddings` sobre o vector de trigramas. Conta as chamadas."""

    def __init__(self) -> None:
        from eval_search import embeddings_falsos

        self.fornecedores = (embeddings_falsos.FORNECEDOR,)
        self.chamadas = 0

    def __call__(self, tenant_id, textos, tecto_s):
        from eval_search import embeddings_falsos
        from kamba_core.idx.embeddings import Vectores

        self.chamadas += 1
        return Vectores(
            embeddings_falsos.MODELO,
            tuple(embeddings_falsos.vector(texto) for texto in textos),
        )


def _envelope(tenant: str, sku: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "tipo": "catalog.product_changed",
        "versao": 2,
        "tenant_id": tenant,
        "agregado": {"tipo": "product", "id": str(uuid.uuid4()), "seq": 1},
        "payload": {"sku": sku, "estado": "publicado"},
    }


def _semear(admin, bd, snapshots: list[str]) -> tuple[dict[str, str], dict[str, dict[str, int]]]:
    from eval_search import dataset
    from kamba_core.idx import consumidor
    from tests import factories

    cursor = admin.cursor()
    tenants: dict[str, str] = {}
    catalogos: dict[str, dict[str, int]] = {}
    for snapshot in snapshots:
        tenant = factories.tenant(cursor)
        factories.aceitar_contratos_vigentes(cursor, tenant)
        cursor.execute("UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s", (tenant,))
        tenants[snapshot] = tenant
        produtos = dataset.ler_catalogo(snapshot)
        catalogos[snapshot] = {str(p["product_ref"]): int(p["preco_minor"]) for p in produtos}
        for produto in produtos:
            cursor.execute(
                "INSERT INTO platform.offer_terms "
                "(tenant_id, sku, nome, preco_tipo, preco_minor, stock_modo, estado) "
                "VALUES (%s, %s, %s, %s, %s, 'garantido', 'publicado')",
                (tenant, produto["sku"], produto["nome"], produto["preco_tipo"], produto["preco_minor"]),
            )
        for produto in produtos:
            consumidor.consumir_evento(bd, _envelope(tenant, str(produto["sku"])))
        # O `idx.candidatos` desempata cada ramo pelo `doc_id`, e o consumidor
        # gera-o ao acaso (`gen_random_uuid`): duas corridas do mesmo *dataset*
        # davam ordens diferentes nos empates — medido, o nDCG@3 de um catalogo
        # mexia 0,016 entre corridas. Fixa-se do *snapshot* e do `product_ref`,
        # e o relatorio passa a ser o mesmo em cada corrida: um vermelho do
        # *gate* e uma regressao, e nao um desempate. O caminho de producao nao
        # muda; so a semente.
        cursor.execute(
            "UPDATE idx.search_doc SET doc_id = md5(%s || ':' || product_ref)::uuid WHERE tenant_id = %s",
            (snapshot, tenant),
        )
        # O preco muda **depois** de indexado, e sem evento: menos 1 Kz em todos.
        # A asercao do preco divergente confere com o preco de agora, e por isso
        # so passa se o numero da resposta vier da oferta viva no instante da
        # pergunta — um indice, uma *cache* ou o ficheiro semeado que fossem a
        # fonte davam o de antes (achado 3 da revisao: conferir com o semeado,
        # sem mudar nada, era quase uma tautologia). Nenhum filtro de preco do
        # *dataset* fica do outro lado com 1 Kz a menos (os tectos sao redondos).
        cursor.execute(
            "UPDATE platform.offer_terms SET preco_minor = preco_minor - %s WHERE tenant_id = %s",
            (AJUSTE_DE_PRECO_MINOR, tenant),
        )
        catalogos[snapshot] = {ref: preco - AJUSTE_DE_PRECO_MINOR for ref, preco in catalogos[snapshot].items()}
    cursor.execute("ANALYZE idx.search_doc")
    cursor.execute("ANALYZE platform.offer_terms")
    return tenants, catalogos


def _embeber(bd, tenants: dict[str, str], cliente) -> dict[str, dict[str, int]]:
    from eval_search import embeddings_falsos
    from kamba_core.idx import embeddings

    voltas: dict[str, dict[str, int]] = {}
    for snapshot, tenant in tenants.items():
        cursor, gravados, recusados = None, 0, 0
        while True:
            # Uma transaccao por volta, com o tenant em `SET LOCAL`: o contexto
            # morre no `COMMIT` e nao passa ao tenant seguinte. O *lint* do
            # *gate* 6 (`tools/isolamento/lints.py`) recusa o `set_config` de
            # sessao, e com razao — foi o vermelho dos *gates* 4, 6 e 8 no #195.
            bd.executar("BEGIN")
            try:
                bd.executar("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
                volta = embeddings.embeber_catalogo(
                    bd, tenant, cliente, embeddings_falsos.MODELO, depois_de=cursor
                )
                bd.executar("COMMIT")
            except BaseException:
                bd.executar("ROLLBACK")
                raise
            if volta.motivo is not None:
                raise RuntimeError(f"{snapshot}: o worker parou com {volta.motivo}")
            gravados += volta.gravados
            recusados += volta.recusados
            if volta.ultimo is None:
                break
            cursor = volta.ultimo
        voltas[snapshot] = {"gravados": gravados, "recusados": recusados}
    return voltas


def _pesquisador(app, tenants, *, vectorial=None, limiar=None):
    from eval_search import runner
    from kamba_core.idx import pesquisa

    def pesquisar(registo):
        argumentos = {"origem": registo.origem, "vectorial": vectorial, "limite": runner.PROFUNDIDADE}
        if limiar is not None:
            argumentos["limiar"] = limiar
        procura = pesquisa.procurar(app, tenants[registo.catalogo], registo.texto, **argumentos)
        tokens = procura.normalizacao.tokens_nao_resolvidos if procura.normalizacao else ()
        return runner.Resposta(procura.linhas, procura.modo, tuple(tokens))

    return pesquisar


def _afinar(app, tenants, catalogos, vectorial) -> dict:
    """Em dev, e so em dev: o `runner.afinar` entra na guarda e confere a divisao."""
    from eval_search import runner
    from kamba_agr.tls.idx import LIMIAR_DO_RRF, score_normalizado
    from kamba_core.idx import pesquisa

    return runner.afinar(
        catalogos=catalogos,
        pesquisador_por_limiar=lambda limiar: _pesquisador(app, tenants, limiar=limiar),
        pesquisador_lexical=_pesquisador(app, tenants),
        pesquisador_hibrido=_pesquisador(app, tenants, vectorial=vectorial),
        limiares_de_palavra=LIMIARES_DE_PALAVRA,
        limiares_do_rrf=LIMIARES_DO_RRF,
        pontuador_lexical=lambda s: score_normalizado(s, hibrido=False),
        pontuador_hibrido=lambda s: score_normalizado(s, hibrido=True),
        actuais={"pg_trgm": pesquisa.LIMIAR_DE_PALAVRA, "rrf": LIMIAR_DO_RRF},
    )


def _dentro(relatorio: str | None) -> int:
    import json

    import bootstrap
    import ligacao
    from eval_search import dataset, embeddings_falsos, runner
    from kamba_core.idx import embeddings
    from tests.base import alembic_ok

    inicio_total = time.perf_counter()
    bootstrap.aplicar()
    alembic_ok("upgrade", "head")
    admin = ligacao.ligar("admin")
    admin.autocommit = True
    cliente_app = ligacao.ligar("app")
    cliente_app.autocommit = True
    bd = _Cliente(cliente_app)
    registos = dataset.ler()
    snapshots = sorted({r.catalogo for r in registos})
    t0 = time.perf_counter()
    tenants, catalogos = _semear(admin, bd, snapshots)
    semeadura_s = round(time.perf_counter() - t0, 1)

    fornecedor = _FornecedorFalso()
    cliente = embeddings.ClienteDeEmbeddings(_PortaLocal(), fornecedor)
    t0 = time.perf_counter()
    voltas = _embeber(bd, tenants, cliente)
    embeber_s = round(time.perf_counter() - t0, 1)
    vectorial = embeddings.ConsultaVectorial(cliente, sensivel=lambda _texto: False)

    app = ligacao.ligar("app")
    execucoes = {
        "lexical": runner.correr(registos, _pesquisador(app, tenants), catalogos, modo="lexical"),
        "hibrido": runner.correr(
            registos, _pesquisador(app, tenants, vectorial=vectorial), catalogos, modo="hibrido"
        ),
    }
    # A afinacao e para quem afina, e nao para o *gate*: sem ela, a corrida e
    # so a das duas passagens (criterio 9, o tempo do relatorio em CI).
    afinacao = None if os.environ.get("KAMBA_GOLDEN_SEM_AFINACAO") else _afinar(app, tenants, catalogos, vectorial)
    manifesto = json.loads(dataset.MANIFESTO.read_text(encoding="utf-8"))
    cursor = admin.cursor()
    cursor.execute("SELECT version()")
    versao_pg = cursor.fetchone()[0]
    dados = runner.relatorio(
        execucoes,
        contexto={
            "rotulo": f"golden_search {manifesto['versao']}, {time.strftime('%Y-%m-%d')}",
            "dataset": manifesto["versao"],
            "consultas": len(registos),
            "catalogos": {s: len(c) for s, c in catalogos.items()},
            "fornecedor_hibrido": embeddings_falsos.MODELO,
            "nota": (
                "Hibrido medido com o fornecedor FALSO (trigramas locais): mede o caminho e "
                "da linha de base de regressao; nao mede modelo de embeddings nenhum. O lexico "
                "PT-AO do KAM-062 nao tem entradas activas na base do gate, pelo que os "
                "regionalismos so contam com o pg_trgm."
            ),
            "embeddings_do_catalogo": voltas,
            "chamadas_ao_fornecedor_falso": fornecedor.chamadas,
            "custo": {"chamadas_pagas": 0, "custo_usd": 0.0},
            "tempos_s": {
                "semeadura": semeadura_s,
                "embeber_catalogo": embeber_s,
                "total": round(time.perf_counter() - inicio_total, 1),
            },
            "postgresql": versao_pg,
            "afinacao": afinacao,
        },
    )
    texto = json.dumps(dados, ensure_ascii=False, indent=2)
    if relatorio:
        runner.escrever(dados, relatorio)
    else:
        print(texto)
    app.close()
    cliente_app.close()
    admin.close()
    from eval_search import gate

    return 0 if gate.verde(dados) else 1


def _correr(ambiente: dict[str, str], _suite: str) -> int:
    argumentos = [sys.executable, str(Path(__file__).resolve()), "--dentro"]
    if os.environ.get("KAMBA_GOLDEN_RELATORIO"):
        argumentos.append(os.environ["KAMBA_GOLDEN_RELATORIO"])
    return subprocess.run(argumentos, cwd=DB, env=ambiente, timeout=1800).returncode


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--dentro":
        return _dentro(argv[1] if len(argv) > 1 else None)
    if "--sem-afinacao" in argv:
        argv = [a for a in argv if a != "--sem-afinacao"]
        os.environ["KAMBA_GOLDEN_SEM_AFINACAO"] = "1"
    if len(argv) > 1:
        print(__doc__, file=sys.stderr)
        return 2
    if argv:
        os.environ["KAMBA_GOLDEN_RELATORIO"] = str(Path(argv[0]).resolve())
    for sinal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sinal, gate_bd._sair_com_limpeza)
    return gate_bd.com_contentor("golden_search", com_fila=False, correr=_correr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
