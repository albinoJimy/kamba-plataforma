"""O ataque as rotas do AGR, conduzido sobre o ASGI em processo.

Separado do `x01_rotas.py` por uma razao que e a razao de ser do pacote: o
`x01_rotas` tem de ser importavel **sem** o AGR (e o que permite medir a
cobertura a seco, sem `starlette` nem `pydantic`), e este modulo importa o AGR.
Por isso o `x01_rotas` importa-o dentro do `fn`, e nao no topo.

## Conduz o ASGI, e nao um cliente HTTP

O `starlette.testclient.TestClient` traria o `httpx`, que o *venv* desta casa
nao tem por causa do AGR — tem-no por causa de mais nada. Uma aplicacao ASGI e
um chamavel de tres argumentos, e conduzi-lo sao trinta linhas: menos uma
dependencia, e nenhuma camada entre o caso e o que a rota devolveu.

## Os duplos nao decidem nada, e e isso que faz a afirmacao forte

O duplo do executor **registra e nao corre**. A pergunta do caso nao e «que
estado devolveu a rota» — e «chegou ao executor um corpo que mistura o tenant
de A com identificadores de B?». Uma rota que o deixasse passar devolvia uma
recusa vinda do executor e passava todas as afirmacoes sobre a resposta, tendo
aceitado a mistura. Por isso o duplo e um registador e o caso le-o.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import sys
import uuid
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[3]


def _no_caminho() -> None:
    for relativo in ("services/agr/src", "libs/py-core/src"):
        caminho = str(RAIZ / relativo)
        if caminho not in sys.path:
            sys.path.insert(0, caminho)


#: A credencial interna do ensaio. Nao e um segredo: a rota compara-a com o que
#: o duplo devolve, e os dois vivem neste ficheiro.
CREDENCIAL = "credencial-interna-do-x01"


class _Registador:
    """Um duplo que registra as chamadas e nao faz nada."""

    def __init__(self, devolver: Any = None) -> None:
        self.chamadas: list[tuple[tuple, dict]] = []
        self._devolver = devolver

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.chamadas.append((args, kwargs))
        return self._devolver

    def sincrono(self, *args: Any, **kwargs: Any) -> Any:
        self.chamadas.append((args, kwargs))
        return self._devolver


def _pedir_com_logs(
    app: Any,
    metodo: str,
    caminho: str,
    corpo: bytes = b"",
    cabecalhos: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], str, str]:
    """`_pedir`, com o que o servico escreveu em `stdout` e `stderr`.

    O criterio 9 pede que o oraculo varra **tambem** os *logs* de cada caso, e
    os *logs* desta casa sao linhas JSON em `stdout` (`kamba_core.logger`). Sem
    esta captura, a origem `logs` do caso varria uma lista vazia — que e varrer
    nada e chamar-lhe cobertura.

    Captura-se `stdout` **e** `stderr`: o `onError` do Hono e o tratador do
    Starlette escrevem no segundo, e e la que uma pilha com um identificador de
    B apareceria.
    """
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(saida):
        estado, resposta_cabecalhos, texto = asyncio.run(
            _pedir(app, metodo, caminho, corpo, cabecalhos)
        )
    return estado, resposta_cabecalhos, texto, saida.getvalue()


async def _pedir(
    app: Any,
    metodo: str,
    caminho: str,
    corpo: bytes = b"",
    cabecalhos: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], str]:
    """`(estado, cabecalhos, corpo)` de um pedido conduzido sobre o ASGI."""
    saida: list[dict] = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": metodo,
        "scheme": "http",
        "path": caminho,
        "raw_path": caminho.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (chave.lower().encode(), valor.encode())
            for chave, valor in (cabecalhos or {}).items()
        ],
        "client": ("127.0.0.1", 0),
        "server": ("ensaio", 80),
    }

    async def receber() -> dict:
        return {"type": "http.request", "body": corpo, "more_body": False}

    async def enviar(mensagem: dict) -> None:
        saida.append(mensagem)

    await app(scope, receber, enviar)

    estado = 0
    resposta_cabecalhos: dict[str, str] = {}
    pedacos: list[bytes] = []
    for mensagem in saida:
        if mensagem["type"] == "http.response.start":
            estado = int(mensagem["status"])
            resposta_cabecalhos = {
                chave.decode(): valor.decode()
                for chave, valor in mensagem.get("headers", [])
            }
        elif mensagem["type"] == "http.response.body":
            pedacos.append(mensagem.get("body", b"") or b"")
    return estado, resposta_cabecalhos, b"".join(pedacos).decode("latin-1")


def _montar(ctx) -> tuple[Any, dict[str, _Registador]]:  # noqa: ANN001
    """O AGR com as quatro rotas internas e duplos em todas as portas."""
    _no_caminho()
    from kamba_agr import api_interna  # noqa: PLC0415
    from kamba_agr.app import create_app  # noqa: PLC0415

    duplos = {
        "executar": _Registador(),
        # O duplo da admissao entra no registo para a sonda positiva o poder
        # ler: e nele que se ve se o corpo coerente de A chegou tao longe.
        "retomar": _Registador(devolver="retomado"),
        "decidir": _Registador(devolver="aprovado"),
        "eventos": _Registador(),
        "aviso": _Registador(),
        "verificar_bot": _Registador(),
    }

    class _Vaga:
        """Uma vaga que se da sempre. A admissao nao e o que este caso mede.

        Serve os dois protocolos — `with` e `async with` — porque o duplo nao
        sabe qual deles o chamador usa, e um `AttributeError` por protocolo
        errado seria mais um achado do andaime.
        """

        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_: Any) -> bool:
            return False

        def __enter__(self) -> None:
            return None

        def __exit__(self, *_: Any) -> bool:
            return False

    class _Admissao:
        """Da vaga, e **recusa o ritmo**. Registra tudo o que lhe chega.

        O ritmo recusado e deliberado, e e o que faz a sonda positiva: o
        `/internal/turn` com um corpo coerente de A passa a autenticacao, passa
        a leitura do contrato, **chega a admissao** e devolve 200 `descartado`
        sem chamar o executor. Isso prova duas coisas de uma vez — a rota esta
        montada (senao as recusas dos ataques nao provavam nada) e o executor
        **nao** foi chamado por nenhum caminho deste caso.
        """

        def __init__(self) -> None:
            self.chamadas: list[Any] = []

        def vaga(self, invocacao: Any) -> Any:
            self.chamadas.append(("vaga", invocacao))
            return _Vaga()

        def vaga_de(self, tenant_id: str, *, prioritario: bool = False) -> Any:
            self.chamadas.append(("vaga_de", tenant_id, prioritario))
            return _Vaga()

        def aceita_o_ritmo(self, _invocacao: Any) -> bool:
            return False

        def deve_avisar(self, _invocacao: Any) -> bool:
            return False

    class _Trancas:
        """Da a tranca, e registra. **Nao recusa**, e a primeira versao recusava.

        Mediu-se: com a tranca a levantar, a sonda positiva do
        `/internal/turn` rebentava com `RuntimeError` em vez de chegar a
        admissao, e o caso reportava um achado que era do andaime. Uma tranca
        recusada e um cenario legitimo — e do KAM-025 e a suite dele mede-o —,
        e nao e o que esta bateria mede.
        """

        def __init__(self) -> None:
            self.chamadas: list[Any] = []

        def tomar(self, *args: Any, **kwargs: Any) -> Any:
            self.chamadas.append((args, kwargs))
            return _Vaga()

        def __getattr__(self, nome: str) -> Any:
            # Qualquer outro metodo da tranca que o AGR venha a chamar devolve
            # o mesmo gestor de contexto permissivo. **Falha aberta de
            # proposito, e so aqui**: um duplo que levante por um metodo novo
            # faz o caso acusar o andaime, e um caso que acusa o andaime ensina
            # a ignorar a lista. O que o caso afirma esta nos duplos
            # registadores (`executar`, `retomar`, `decidir`), nao aqui.
            def permissivo(*_args: Any, **_kwargs: Any) -> Any:
                self.chamadas.append((nome, _args, _kwargs))
                return _Vaga()

            return permissivo

    admissao = _Admissao()
    duplos["admissao"] = admissao
    rotas = api_interna.rotas(
        credencial=lambda: CREDENCIAL,
        executar=duplos["executar"],
        admissao=admissao,
        trancas=_Trancas(),
        retomar=duplos["retomar"],
        # **O verificador do *agent bot* recusa, e `None` nao e recusar.** A
        # primeira versao devolvia `None` a pensar que era «nao autorizado», e
        # e o contrario: a funcao devolve o **motivo** quando recusa, pelo que
        # `None` autorizava tudo. Medido — a `/internal/draft-decision` passava
        # a autenticacao, chegava ao `decidir` e rebentava com `AttributeError`
        # no duplo. Quem ataca nao tem o `secret` do *agent bot* (e um segredo
        # por conta do HND, nao do tenant), pelo que a postura certa do ataque e
        # a recusa — e e ela que faz valer a afirmacao de que os duplos de
        # `retomar` e de `decidir` **nao** foram chamados.
        verificar_bot=lambda _cabecalho, _thread: "secret_errado",
        aviso=duplos["aviso"].sincrono,
        eventos=None,
        decidir=duplos["decidir"],
    )
    return create_app(rotas_internas=rotas), duplos


def _corpos_com_ids_de_b(ctx) -> dict[str, list[dict]]:  # noqa: ANN001
    """Por caminho, os corpos que misturam o tenant de A com coisas de B.

    ## O que «A usa IDs de B» quer dizer **nesta** superficie

    A `/internal/*` do AGR nao tem identidade de tenant: a credencial e **da
    instancia** (`agr_internal_token`) e quem chama e o nosso proprio *shim*
    (ADR-L004). Nao ha, portanto, um «A autenticado» a pedir o recurso de B — e
    um corpo inteiramente de B nao e um ataque, e um pedido legitimo pelo
    tenant B, que foi o que a primeira versao deste caso enviou (e que, com
    razao, devolveu o mesmo 200 `descartado` de qualquer corpo coerente, a
    quebrar a uniformidade por nao ser um ataque).

    O que e um ataque aqui e a **mistura**: um corpo em que o `tenant_id` e de
    um e os identificadores sao de outro. E a unica forma de um chamador — ou de
    um modelo que lhe tenha chegado ao corpo — pedir o recurso de B pela via de
    A. E e precisamente o que o `thread_id` fecha: ele e derivado de
    `(tenant_id, contact_id)`, pelo que a mistura **nao tem `thread_id`
    valido** e e recusada antes de qualquer leitura (`thread_id_incoerente`).

    Duas variantes por caminho: a mistura crua, e a mistura com o canario de B
    posto num campo de texto livre — para que o oraculo tenha o que procurar nas
    mensagens de erro, que e por onde a fuga sairia.
    """
    a, b = ctx.a.id, ctx.b.id
    contacto_de_b = str(uuid.uuid5(uuid.NAMESPACE_URL, f"kamba-x01:{b}"))
    canario_de_b = next(iter(ctx.oraculo.proibidos.values()))
    thread_de_b = f"{b}:{contacto_de_b}"

    def _invocacao(**sobrepor: Any) -> dict:
        corpo = {
            "tenant_id": a,
            "contact_id": contacto_de_b,
            "conversation_id": str(uuid.uuid4()),
            "channel_id": str(uuid.uuid4()),
            "wamid": "wamid.HBgMMjQ0OTAwMDAwMDAwFQIAEhgg" + uuid.uuid4().hex[:8],
            "type": "text",
            "modo": "bot",
            "thread_id": thread_de_b,
            "vertical": "vendedor",
        }
        corpo.update(sobrepor)
        return corpo

    return {
        "/internal/turn": [
            _invocacao(),
            _invocacao(wamid="wamid." + canario_de_b),
        ],
        "/internal/resume": [
            {"thread_id": thread_de_b, "handoff_id": str(uuid.uuid4()), "outcome": "resolved"},
            {"thread_id": thread_de_b, "handoff_id": canario_de_b, "outcome": "resolved"},
        ],
        "/internal/event": [
            {"event_id": str(uuid.uuid4()), "tenant_id": b, "tipo": "payment.confirmed"},
            {"event_id": canario_de_b, "tenant_id": b, "tipo": "payment.confirmed"},
        ],
        "/internal/draft-decision": [
            {"thread_id": thread_de_b, "draft_id": uuid.uuid4().hex, "decisao": "aprovado"},
            {"thread_id": thread_de_b, "draft_id": canario_de_b, "decisao": "aprovado"},
        ],
    }


def _corpo_inexistente(caminho: str) -> dict:
    """Um corpo que difere dos ataques **so** na existencia dos identificadores.

    O controlo do achado 19, e a primeira versao dele estava errada — a
    execucao do *gate* mostrou-o. Ela mandava um corpo **coerente** (tenant,
    contacto e `thread_id` do mesmo tenant inventado), e a `/internal/turn`
    respondeu-lhe **200 `descartado`** contra os 400 dos ataques. A diferenca
    era real e nao era a que se queria medir: media **coerencia contra
    incoerencia**, nao existencia contra inexistencia, e fazia o caso acusar um
    oraculo de existencia que nao existe.

    Um controlo so serve se diferir do ataque numa variavel. Os ataques misturam
    o tenant de A com o `thread_id` de B; este mistura **dois tenants
    inventados** — o `thread_id` deriva de um par que nao e o que vai no
    `tenant_id` —, pelo que e incoerente da mesma maneira. O que sobra como
    diferenca e a unica coisa que interessa: os identificadores do ataque
    existem e os deste nao.
    """
    tenant = str(uuid.uuid4())
    contacto = str(uuid.uuid4())
    # O `thread_id` de **outro** par inventado: a mesma incoerencia dos ataques.
    thread = f"{uuid.uuid4()}:{uuid.uuid4()}"
    comuns = {
        "/internal/turn": {
            "tenant_id": tenant,
            "contact_id": contacto,
            "conversation_id": str(uuid.uuid4()),
            "channel_id": str(uuid.uuid4()),
            "wamid": "wamid.HBgMMjQ0OTAwMDAwMDAwFQIAEhgg" + uuid.uuid4().hex[:8],
            "type": "text",
            "modo": "bot",
            "thread_id": thread,
            "vertical": "vendedor",
        },
        "/internal/resume": {
            "thread_id": thread,
            "handoff_id": str(uuid.uuid4()),
            "outcome": "resolved",
        },
        "/internal/event": {
            "event_id": str(uuid.uuid4()),
            "tenant_id": tenant,
            "tipo": "payment.confirmed",
        },
        "/internal/draft-decision": {
            "thread_id": thread,
            "draft_id": uuid.uuid4().hex,
            "decisao": "aprovado",
        },
    }
    return comuns[caminho]


#: Caminho -> o identificador do item enumerado. Uma so fonte para os dois.
ITEM_DE = {
    "/internal/turn": "rota:agr:kamba_agr/api_interna:rotas:POST:/internal/turn",
    "/internal/resume": "rota:agr:kamba_agr/api_interna:rotas:POST:/internal/resume",
    "/internal/event": "rota:agr:kamba_agr/api_interna:rotas:POST:/internal/event",
    "/internal/draft-decision": (
        "rota:agr:kamba_agr/api_interna:rotas:POST:/internal/draft-decision"
    ),
}


def atacar_rotas_internas(ctx) -> list[str]:  # noqa: ANN001
    """O X-01 das quatro rotas internas do AGR."""
    from .x01_rotas import _uniformidade  # noqa: PLC0415

    app, duplos = _montar(ctx)
    admissao = duplos["admissao"]
    achados: list[str] = []

    for caminho, corpos in _corpos_com_ids_de_b(ctx).items():
        item = ITEM_DE[caminho]
        estados: list[int] = []
        for corpo in corpos:
            estado, cabecalhos, texto, registo = _pedir_com_logs(
                app,
                "POST",
                caminho,
                json.dumps(corpo).encode(),
                {"content-type": "application/json", "x-kamba-interno": CREDENCIAL},
            )
            ctx.logs.append(registo)
            estados.append(estado)
            achados.extend(
                f"{item}: {fuga}"
                for fuga in ctx.oraculo.varrer_tudo(
                    {"corpo": texto, "cabecalhos": cabecalhos, "logs": ctx.logs}
                )
            )
        # **O controlo: um identificador que nao existe em tenant nenhum.**
        #
        # E o que faltava, e a revisao adversarial apontou-o: o oraculo de
        # existencia que importa nao e a diferenca entre duas rotas, e a
        # diferenca entre **o identificador de B (que existe)** e um que nao
        # existe. Uma rota que devolvesse 403 a todos os de B e 404 a um UUID
        # inventado passava a uniformidade — um so estado distinto entre os
        # ataques — e entregava, pela diferenca, exactamente o que o criterio
        # existe para esconder.
        estado_de_controlo, _, _, _ = _pedir_com_logs(
            app,
            "POST",
            caminho,
            json.dumps(_corpo_inexistente(caminho)).encode(),
            {"content-type": "application/json", "x-kamba-interno": CREDENCIAL},
        )
        # A uniformidade mede-se **entre os ataques**; o controlo compara-se a
        # parte. Metê-lo no mesmo conjunto juntava duas perguntas diferentes num
        # achado so, e a mensagem dizia «identificadores de B» sobre um estado
        # que nao vinha de nenhum.
        achados.extend(_uniformidade(item, estados))
        if estados and estado_de_controlo not in estados:
            achados.append(
                f"{item}: os identificadores de B deram {sorted(set(estados))} e "
                f"um identificador que **nao existe** deu {estado_de_controlo}, "
                "com a mesma forma de corpo. A diferenca e um oraculo de "
                "existencia: quem ataca aprende, por ela, que o recurso de B "
                "existe — que e o que o criterio 3 pede para esconder ao exigir "
                "recusas uniformes."
            )

    # A afirmacao que a resposta nao da: o executor nao recebeu nada.
    for nome in ("executar", "retomar", "decidir"):
        chamadas = duplos[nome].chamadas
        if chamadas:
            achados.append(
                f"X-01/agr: o duplo de `{nome}` foi chamado {len(chamadas)} "
                "vez(es) com um corpo que mistura tenants. A rota devolveu uma "
                "recusa, mas aceitou a mistura antes de a devolver — e a "
                "proxima versao do executor pode nao a recusar."
            )

    # A metade positiva: com o corpo bem formado de A, a rota **chega** ao
    # executor. Sem isto, as afirmacoes acima passavam com uma rota que recusa
    # tudo — ou que nem existe.
    corpo_de_a = {
        "tenant_id": ctx.a.id,
        "contact_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "channel_id": str(uuid.uuid4()),
        "wamid": "wamid.HBgMMjQ0OTAwMDAwMDAwFQIAEhgg" + uuid.uuid4().hex[:8],
        "type": "text",
        "modo": "bot",
        "thread_id": "",
        "vertical": "vendedor",
    }
    from kamba_agr.contexto import thread_id_de  # noqa: PLC0415

    corpo_de_a["thread_id"] = thread_id_de(ctx.a.id, corpo_de_a["contact_id"])
    estado, _, _, _ = _pedir_com_logs(
        app,
        "POST",
        "/internal/turn",
        json.dumps(corpo_de_a).encode(),
        {"content-type": "application/json", "x-kamba-interno": CREDENCIAL},
    )
    # **A sonda afirma que o corpo de A **chega a admissao**, e nao so que
    # nao deu 404.** A primeira versao verificava `estado == 404` e mais
    # nada: uma regressao de validacao que recusasse todo o corpo com 400
    # deixava os quatro ataques a dar 400 uniforme (que esta em
    # `RECUSAS_ACEITAVEIS`), os duplos nunca chamados (que passa a asserção
    # acima) e a sonda verde porque 400 != 404 — caso verde, zero medicao.
    # Achado 11 da revisao adversarial. O duplo da admissao registra, e e
    # nele que se le se o corpo chegou la.
    if estado == 404:
        achados.append(
            "X-01/agr: a sonda positiva falhou — um corpo coerente de A tambem "
            "deu 404. A rota nao esta montada, e as recusas acima nao provam "
            "isolamento nenhum."
        )
    elif not admissao.chamadas:
        achados.append(
            f"X-01/agr: a sonda positiva falhou — um corpo coerente de A deu "
            f"{estado} e **nao chegou a admissao**. As recusas dos ataques "
            "podem ser da mesma causa que esta, e nesse caso nao medem "
            "isolamento nenhum: medem que a rota recusa tudo."
        )
    return achados


def atacar_sonda(ctx) -> list[str]:  # noqa: ANN001
    """O X-01 da `/healthz` do AGR: responde, e nao leva nada de B."""
    app, _ = _montar(ctx)
    estado, cabecalhos, texto, registo = _pedir_com_logs(app, "GET", "/healthz")
    ctx.logs.append(registo)
    achados: list[str] = []
    if estado != 200:
        achados.append(
            f"rota:agr:…/healthz: a sonda respondeu {estado} e nao 200; o caso "
            "nao mediu o que queria medir."
        )
    achados.extend(
        f"rota:agr:…/healthz: {fuga}"
        for fuga in ctx.oraculo.varrer_tudo(
            {"corpo": texto, "cabecalhos": cabecalhos, "logs": ctx.logs}
        )
    )
    return achados


def atacar_metricas(ctx) -> list[str]:  # noqa: ANN001
    """O X-01 da `/metrics` do AGR (KAM-080): responde, e nao leva nada de B.

    A rota nasceu com o KAM-080 — o AGR declarava 44 metricas e nao servia
    nenhuma. E entra nesta bateria pela razao que o `x01_rotas` escreve para as
    metricas em TypeScript: *«uma rota de sonda nao escapa ao criterio por nao
    ter argumentos: ela responde, e o que ela responde atravessa o oraculo como
    qualquer outra»*.

    **Aqui a afirmacao e mais forte do que numa sonda**, e e por isso que o caso
    e proprio e nao uma linha na lista da sonda: o corpo da `/healthz` sao quatro
    campos fixos, e o da `/metrics` e **tudo o que o processo contou**. Se um dia
    alguem acrescentar uma etiqueta por *tenant* a uma das 44 — que e exactamente
    o que o `OBS-I` proibe e o `obs_lint` recusa no catalogo —, e aqui que isso
    fica vermelho, porque o oraculo varre o corpo a procura dos identificadores
    de B.

    **O caso conta antes de ler**, e nao e detalhe: o `exposicao()` do AGR nao
    emite series a zero (`if not series: continue`), pelo que um processo fresco
    serve corpo **vazio** — e um oraculo sobre um corpo vazio nao mede nada.
    Conta-se um turno, e o que se afirma e que nada de B aparece no texto
    servido.

    **Monta `create_app()` sem rotas internas, e nao o `_montar` desta
    bateria**, que e o que os outros casos do AGR usam. Nao e atalho: a
    `/metrics` **nao depende** das portas — o registo de metricas vive em
    memoria —, e o `_montar` importa o `api_interna`, que arrasta o `yaml`, o
    `pydantic` e o registo das verticais. Pedir-lhe isso era fazer este caso
    depender de meio AGR para ler um contador, e um caso que precisa de mais do
    que mede e um caso que falha por razoes que nao sao a sua.
    """
    _no_caminho()
    from kamba_agr import metricas as modulo  # noqa: PLC0415
    from kamba_agr.app import create_app  # noqa: PLC0415

    app = create_app()

    # Conta algo, para que haja series. Os valores de etiqueta do AGR vem de
    # listas fechadas, pelo que isto nao injecta identificador nenhum — o que
    # injectaria seria a gramatica do `contar` a ceder, e ela nao cede.
    modulo.METRICAS.contar(modulo.METRICA_TURNOS, "executado")

    estado, cabecalhos, texto, registo = _pedir_com_logs(app, "GET", "/metrics")
    ctx.logs.append(registo)

    achados: list[str] = []
    if estado != 200:
        achados.append(
            f"rota:agr:…/metrics: respondeu {estado} e nao 200; o caso nao mediu "
            "o que queria medir."
        )
    if "# TYPE" not in texto:
        achados.append(
            "rota:agr:…/metrics: o corpo nao traz `# TYPE`, logo nao ha series e "
            "o oraculo varreria o vazio. O caso tem de contar antes de ler."
        )
    achados.extend(
        f"rota:agr:…/metrics: {fuga}"
        for fuga in ctx.oraculo.varrer_tudo(
            {"corpo": texto, "cabecalhos": cabecalhos, "logs": ctx.logs}
        )
    )
    return achados
