"""A fase `exportacao` do off-boarding (KAM-098, criterio 4).

O pacote do titular: clientes, encomendas, conversas, consentimentos, a lista
dos ficheiros no STO e o catalogo (quando ha fonte), em **JSON e CSV**, com um
manifesto que leva o `sha256` de cada ficheiro, num ZIP reproduzivel que fica no
STO. A ligacao ao titular vale 24 h (*proposta*) e cada geracao e auditada; uma
geracao nova faz-se a pedido.

## As consultas correm com o papel da aplicacao e o contexto do tenant

O bloco: «consulta sob `app.tenant_id`». A ligacao e a do `kamba_app`, a
transaccao e o `tenant_guard.tx` (que define o contexto), e **cada consulta
filtra tambem pelo tenant** no texto: com a RLS `FORCE`, a politica `tenant_iso`
ja da zero linhas de outro tenant, e o predicado no texto e a segunda barreira,
a que vale se alguem correr isto com o papel errado (o `kamba_batch` contorna a
RLS). O isolamento mede-se pelo ensaio cruzado (exportacao de A sem nada de B).

## O que nao sai, e e lacuna declarada

* **O telefone e o BSUID dos clientes.** Vivem cifrados no `contact_endpoints`,
  que so o `kamba_identity` le, e decifra-los exige a DEK — a mesma lacuna da
  exportacao do titular do KAM-070, com o mesmo credor. O bloco pede «telefones
  decifrados so para campos exportaveis, com auditoria»: fica por fazer.
* **O catalogo da Medusa**, quando nao ha fonte: o registo de produtos da opcao
  B da D3 nao existe (o KAM-042 deixou o `RegistoAdmin` sem cliente, e a D3 esta
  por ratificar). Com `fonte_do_catalogo`, entra; sem ela, o manifesto diz
  `indisponivel` com a razao, em vez de um ficheiro vazio que parecia um
  catalogo sem produtos. **O que a plataforma guarda do catalogo sai sempre**
  (KAM-218): as `ofertas` (a `offer_terms`, termos comerciais por SKU) e os
  `aceites` (a prova de aceite do KAM-090).
* **O texto das conversas**: esta base guarda de cada conversa o canal, o
  modo e as janelas, e nao o texto — o CHR nao o guarda, e as mensagens vivem
  no Chatwoot (o espelho do KAM-019). A coleccao `conversas` sai com os
  metadados, e o texto e do credor (KAM-210, criterio 4).
* **Os ficheiros em si, acima de um tecto**: o pacote leva a lista dos objectos
  do tenant no STO (chave e tamanho) e, desde o KAM-210, **os bytes** de cada um
  em `objectos/<chave>`, com o `sha256` no manifesto. Acima de
  `TECTO_DOS_BYTES` (*proposta*) os bytes nao entram, e o manifesto di-lo em
  `indisponiveis` com a razao, em vez de um pacote que nao cabe num pedido ou
  de uma exportacao que nunca acaba (e com ela a revogacao, que a espera).

## A suspensao nao bloqueia a exportacao (KAM-058, criterio 7)

Esta funcao **nao le o estado do tenant**: exporta de um tenant `ativo`,
`suspenso` ou `encerrado`, porque o que a autoriza e o pedido verificado e os
pendentes fechados, e nao o estado. E o que o encerramento por decisao de T&S
(`suspenso -> encerrado`) precisa, e e o que o KAM-058 deixou por ensaiar.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import zipfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Final

from .. import tenant_guard
from ..direitos.exportacao import CLASSE_DA_EXPORTACAO, documento, resumo
from ..storage.chave import nova_chave
from ..storage.guarda import LIMITE_MAXIMO_DE_LISTAGEM
from ..storage.port import TTL_MAXIMO_S, Ctx, ObjectMeta, ObjectRef, StorageProvider
from .contrato import (
    FaseForaDeOrdem,
    LigacaoRecusada,
    auditar,
    exigir_concluida,
    exigir_pedido_vivo,
    ler_fases,
    marcar,
)

#: A versao do manifesto, em SemVer (bloco: «formato estruturado estavel»). Sobe
#: o *major* quando um campo muda de sentido ou sai; o *minor* quando entra um.
#: 1.1.0 (KAM-210): os bytes dos objectos do STO em `objectos/<chave>`.
#: 1.2.0 (KAM-218): as coleccoes `ofertas` e `aceites`.
VERSAO_DO_MANIFESTO: Final = "1.2.0"

#: O tecto dos bytes dos objectos dentro do pacote. *Proposta*, sem medicao: o
#: pacote monta-se em memoria no processo dos dados. Acima dele, os bytes ficam
#: de fora e o manifesto di-lo (`RAZAO_ACIMA_DO_TECTO`).
#:
#: **48 MiB, e nao os 256 do KAM-210** (achado 3 da revisao adversarial do
#: KAM-218). Os bytes vivem tres vezes ao mesmo tempo — os `conteudos`, a copia
#: no ZIP e o ZIP inteiro — e o processo tem 256 MiB no *compose*, que e o que a
#: folga do orcamento de memoria de producao comporta (o `conjunto-reduzido`
#: estava a 358 MiB do tecto dos 80%). Com 256 MiB de tecto, um tenant com 60 MiB
#: de fotos matava o processo por falta de memoria em cada volta, e a exportacao
#: nunca concluia.
#: shortcut: os bytes acima de 48 MiB ficam fora do pacote; reve-se quando o
#: pacote passar a escrever-se em fluxo para o STO, ou com a primeira medicao.
TECTO_DOS_BYTES: Final = 48 * 1024 * 1024

#: A razao dos bytes em falta, quando passam do tecto.
RAZAO_ACIMA_DO_TECTO: Final = (
    "os objectos do armazenamento passam o tecto do pacote; a lista vai em ficheiros.json "
    "e cada objecto pede-se a parte"
)

#: Quanto vale a ligacao ao titular. *Proposta* (bloco: «24 h»).
VALIDADE_DA_LIGACAO: Final = timedelta(hours=24)

#: O instante dentro do ZIP. Fixo, para o mesmo conteudo dar o mesmo `sha256`.
_INSTANTE_DO_ZIP: Final = (1980, 1, 1, 0, 0, 0)

#: As coleccoes que vem da base, pela ordem do manifesto, com a consulta de cada
#: uma. **Cada consulta filtra pelo tenant no texto** (ver a nota do modulo), e
#: um ensaio itera este mapa e exige o predicado em todas.
COLECCOES: Final[Mapping[str, str]] = {
    "clientes": """
      SELECT contact_id, criado_at, erased_at, merged_into, merged_at
        FROM platform.contacts
       WHERE tenant_id = %s::uuid
       ORDER BY criado_at, contact_id
    """,
    "encomendas": """
      SELECT id, contact_id, numero_publico, estado, total_minor, currency,
             lines_snapshot, entrega_modo, paga_at, paga_via, entregue_at,
             deleted_at, criado_at
        FROM platform.orders_mirror
       WHERE tenant_id = %s::uuid
       ORDER BY criado_at, id
    """,
    "conversas": """
      SELECT id, contact_id, channel_id, mode, last_inbound_at, window_expires_at
        FROM platform.conversations
       WHERE tenant_id = %s::uuid
       ORDER BY id
    """,
    "consentimentos": """
      SELECT contact_id, purpose, accepted, text_version, ocorrido_em
        FROM platform.consent_actual
       WHERE tenant_id = %s::uuid
       ORDER BY contact_id, purpose
    """,
    # KAM-218: as ofertas do tenant — o que a plataforma guarda do catalogo
    # (os termos comerciais por SKU, a revisao `0028`). O registo de produtos
    # da opcao B da D3 (a Medusa) nao existe, e continua `indisponivel` no
    # manifesto (`RAZAO_SEM_CATALOGO`): estas linhas nao fingem ser ele. As
    # apagadas e as arquivadas saem tambem, com a coluna que o diz — sao
    # dados do titular.
    "ofertas": """
      SELECT sku, nome, preco_tipo, preco_minor, currency, preco_valido_ate,
             stock_modo, stock_verificado_at, estado, criado_at, atualizado_at,
             deleted_at
        FROM platform.offer_terms
       WHERE tenant_id = %s::uuid
       ORDER BY sku
    """,
    # KAM-218: a prova de aceite do KAM-090 — cada documento aceite, a versao,
    # o `sha256` do texto e o `evidence_hash` que o `CHECK` da `0040` amarra ao
    # signatario, ao instante e ao desafio do OTP. O prefixo do IP fica de
    # fora: e um resumo de rede, e nao prova nada a quem recebe o pacote.
    "aceites": """
      SELECT document_id, versao, doc_sha256, signatario_ref, otp_challenge_id,
             aceite_em, evidence_hash
        FROM platform.contract_acceptance
       WHERE tenant_id = %s::uuid
       ORDER BY aceite_em, document_id, versao
    """,
}

#: A razao do catalogo em falta, quando nao ha fonte.
RAZAO_SEM_CATALOGO: Final = (
    "o registo de produtos da opcao B da D3 (a Medusa) nao existe nesta plataforma; "
    "os termos comerciais por SKU saem em ofertas"
)

#: A fonte do catalogo: o tenant, e as linhas. Nenhuma implementacao ainda.
FonteDoCatalogo = Callable[[str], Sequence[Mapping[str, Any]]]
AbrirLigacao = Callable[[], Any]


def _linhas(cursor: Any) -> list[dict[str, Any]]:
    colunas = [d[0] for d in cursor.description]
    return [dict(zip(colunas, linha, strict=True)) for linha in cursor.fetchall()]


def _valor_csv(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (dict, list)):
        return json.dumps(valor, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    if isinstance(valor, datetime):
        return valor.isoformat()
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return bytes(valor).hex()
    return str(valor)


def _csv(linhas: Sequence[Mapping[str, Any]]) -> bytes:
    colunas = sorted({c for linha in linhas for c in linha})
    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow(colunas)
    for linha in linhas:
        escritor.writerow([_valor_csv(linha.get(c)) for c in colunas])
    return saida.getvalue().encode("utf-8")


def montar_pacote(
    tenant_id: str,
    coleccoes: Mapping[str, Sequence[Mapping[str, Any]]],
    objectos: Sequence[ObjectRef],
    gerado_at: datetime,
    *,
    indisponiveis: Mapping[str, str] | None = None,
    conteudos: Mapping[str, bytes] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """O ZIP e o manifesto. Puro e reproduzivel: o mesmo conteudo da o mesmo `sha256`.

    Cada coleccao sai em `<nome>.json` (documento canonico) e `<nome>.csv`; a
    lista dos objectos do STO em `ficheiros.json`, e os bytes de cada um (quando
    `conteudos` os traz) em `objectos/<chave>`. O manifesto leva, por
    ficheiro, o nome, o `sha256` e os bytes, e por coleccao o numero de linhas.
    O `sha256` do pacote calcula quem o recebe sobre o ZIP inteiro; o do
    manifesto vai no `resultado` da fase.
    """
    ficheiros: dict[str, bytes] = {}
    contagens: dict[str, int] = {}
    for nome, linhas in coleccoes.items():
        ficheiros[f"{nome}.json"] = documento({"coleccao": nome, "linhas": list(linhas)})
        ficheiros[f"{nome}.csv"] = _csv(linhas)
        contagens[nome] = len(linhas)
    lista = [{"chave": str(o.key), "bytes": o.tamanho} for o in sorted(objectos, key=lambda o: str(o.key))]
    ficheiros["ficheiros.json"] = documento({"coleccao": "ficheiros", "linhas": lista})
    contagens["ficheiros"] = len(lista)
    for chave, conteudo in (conteudos or {}).items():
        ficheiros[f"objectos/{chave}"] = bytes(conteudo)
    manifesto = {
        "versao": VERSAO_DO_MANIFESTO,
        "tenant_id": tenant_id,
        "gerado_at": gerado_at.isoformat(),
        "coleccoes": contagens,
        "indisponiveis": [
            {"coleccao": c, "razao": r} for c, r in sorted((indisponiveis or {}).items())
        ],
        "ficheiros": [
            {"nome": n, "sha256": resumo(b), "bytes": len(b)} for n, b in sorted(ficheiros.items())
        ],
    }
    corpo = io.BytesIO()
    with zipfile.ZipFile(corpo, "w", compression=zipfile.ZIP_DEFLATED) as zipado:
        for nome, conteudo in [("manifesto.json", documento(manifesto)), *sorted(ficheiros.items())]:
            info = zipfile.ZipInfo(nome, date_time=_INSTANTE_DO_ZIP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zipado.writestr(info, conteudo)
    return corpo.getvalue(), manifesto


def exportar(
    abrir_batch: AbrirLigacao,
    abrir_app: AbrirLigacao,
    tenant_id: str,
    armazenamento: StorageProvider,
    agora: datetime,
    *,
    fonte_do_catalogo: FonteDoCatalogo | None = None,
) -> dict[str, Any]:
    """Gera o pacote do tenant e conclui a fase `exportacao` (uma geracao nova a cada chamada).

    Exige o pedido vivo e os pendentes concluidos («sem pendentes, a exportacao
    arranca»), e recusa depois da purga (ja nao ha o que exportar). Devolve a
    referencia do pacote, o `sha256` do pacote e o do manifesto.
    """
    tenant_id = tenant_guard.normalizar_tenant(tenant_id)

    def antes(cursor: Any) -> Any:
        fases = ler_fases(cursor, tenant_id)
        exigir_pedido_vivo(fases, "exportacao")
        exigir_concluida(fases, "pendentes", "exportacao")
        if fases["purga"].estado == "concluida":
            raise FaseForaDeOrdem("a fase exportacao nao pode correr: a purga ja correu")
        return fases["purga"].prazo_at

    expira = _em_batch(abrir_batch, "offboarding_exportacao", antes)

    ligacao = abrir_app()
    try:
        with tenant_guard.tx(ligacao, tenant_id) as cursor:
            coleccoes: dict[str, list[dict[str, Any]]] = {}
            for nome, sql in COLECCOES.items():
                cursor.execute(sql, (tenant_id,))
                coleccoes[nome] = _linhas(cursor)
    finally:
        ligacao.close()

    indisponiveis: dict[str, str] = {}
    if fonte_do_catalogo is None:
        indisponiveis["catalogo"] = RAZAO_SEM_CATALOGO
    else:
        coleccoes["catalogo"] = [dict(linha) for linha in fonte_do_catalogo(tenant_id)]

    ctx = Ctx(tenant_id)
    objectos = [
        # Ate ao maximo da guarda, e nao o limite por omissao de 1 000 (achado 5):
        # a listagem recusa acima dele, e a exportacao falhava em todas as voltas.
        # shortcut: acima de 10 000 objectos a exportacao falha e a fase fica
        # parada, com alerta; revê-se com a paginacao da porta do armazenamento.
        o for o in armazenamento.list(ctx, f"t/{tenant_id}/", limite=LIMITE_MAXIMO_DE_LISTAGEM)
        # Os pacotes de geracoes anteriores nao entram no seguinte.
        if f"/{CLASSE_DA_EXPORTACAO}/" not in str(o.key)
    ]
    conteudos: dict[str, bytes] = {}
    if sum(max(o.tamanho, 0) for o in objectos) > TECTO_DOS_BYTES:
        indisponiveis["objectos"] = RAZAO_ACIMA_DO_TECTO
    else:
        for o in objectos:
            conteudos[str(o.key)] = b"".join(armazenamento.get(ctx, o))
    pacote, manifesto = montar_pacote(
        tenant_id, coleccoes, objectos, agora, indisponiveis=indisponiveis, conteudos=conteudos
    )
    ref = armazenamento.put(
        ctx,
        nova_chave(ctx, CLASSE_DA_EXPORTACAO, agora),
        pacote,
        # O pacote nao sobrevive a purga: expira no prazo dela.
        ObjectMeta("application/zip", CLASSE_DA_EXPORTACAO, expira),
    )
    sha_pacote = resumo(pacote)
    sha_manifesto = resumo(documento(manifesto))

    def depois(cursor: Any) -> int:
        fases = ler_fases(cursor, tenant_id)
        # Um cancelamento que acabou enquanto o pacote se montava ganha: nao se
        # marca concluida uma fase de um pedido cancelado (achado 5).
        exigir_pedido_vivo(fases, "exportacao")
        anterior = fases["exportacao"].resultado
        geracao = int(anterior.get("geracoes", 0)) + 1
        marcar(cursor, tenant_id, "exportacao", "concluida", {
            "geracoes": geracao,
            "versao_do_manifesto": VERSAO_DO_MANIFESTO,
            "sha256": sha_pacote,
            "manifesto_sha256": sha_manifesto,
            "chave": str(ref.key),
            "gerado_at": agora.isoformat(),
        })
        auditar(cursor, tenant_id, "exportacao", f"geracao:{geracao}:{sha_pacote}")
        return geracao

    geracao = _em_batch(abrir_batch, "offboarding_exportacao", depois)
    return {
        "ref": ref,
        "sha256": sha_pacote,
        "manifesto_sha256": sha_manifesto,
        "geracao": geracao,
        "manifesto": manifesto,
    }


def _em_batch(abrir: AbrirLigacao, job: str, trabalho: Callable[[Any], Any]) -> Any:
    ligacao = abrir()
    try:
        with tenant_guard.tx_batch(ligacao, job) as cursor:
            return trabalho(cursor)
    finally:
        ligacao.close()


# ------------------------------------------------------------------ a ligacao


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode("ascii")


def _de_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def ligacao_assinada(chave_hmac: bytes, tenant_id: str, chave_do_objecto: str, agora: datetime) -> str:
    """A ligacao de 24 h ao pacote: um *token* HMAC-SHA256 com o tenant, o objecto e a validade.

    **Nao e o URL do STO**, que o `sign_url` limita a `TTL_MAXIMO_S` (5 min) e
    bem: o *token* e o que o titular guarda por 24 h, e cada abertura assina um
    URL novo de 5 min (`abrir_ligacao`). Gerar outra ligacao e chamar isto outra
    vez; a anterior continua ate expirar.
    """
    if len(chave_hmac) < 32:
        raise ValueError("a chave da ligacao tem pelo menos 32 bytes")
    corpo = documento({
        "t": tenant_guard.normalizar_tenant(tenant_id),
        "k": chave_do_objecto,
        "e": int((agora + VALIDADE_DA_LIGACAO).timestamp()),
    })
    mac = hmac.new(chave_hmac, corpo, hashlib.sha256).digest()
    return f"{_b64(corpo)}.{_b64(mac)}"


def abrir_ligacao(
    chave_hmac: bytes,
    token: str,
    tenant_do_pedido: str,
    agora: datetime,
    armazenamento: StorageProvider,
) -> str:
    """O URL do STO para um *token* valido; `LigacaoRecusada` (403) para todos os outros.

    Recusa, sem dizer qual das razoes: a assinatura nao confere, o *token* e de
    outro tenant, ou expirou. Dizer qual ensinava a quem forja o que mudar.
    """
    try:
        corpo_b64, mac_b64 = token.split(".", 1)
        corpo, mac = _de_b64(corpo_b64), _de_b64(mac_b64)
        esperado = hmac.new(chave_hmac, corpo, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, esperado):
            raise LigacaoRecusada("ligacao recusada")
        dados = json.loads(corpo)
        tenant = tenant_guard.normalizar_tenant(tenant_do_pedido)
        if dados["t"] != tenant or int(dados["e"]) <= int(agora.timestamp()):
            raise LigacaoRecusada("ligacao recusada")
    except LigacaoRecusada:
        raise
    except Exception as erro:  # noqa: BLE001 — um token ilegivel e um 403, nao um 500
        raise LigacaoRecusada("ligacao recusada") from erro
    return armazenamento.sign_url(Ctx(tenant), ObjectRef(dados["k"], 0), ttl_seconds=TTL_MAXIMO_S)


__all__ = [
    "COLECCOES",
    "RAZAO_ACIMA_DO_TECTO",
    "RAZAO_SEM_CATALOGO",
    "TECTO_DOS_BYTES",
    "VALIDADE_DA_LIGACAO",
    "VERSAO_DO_MANIFESTO",
    "abrir_ligacao",
    "exportar",
    "ligacao_assinada",
    "montar_pacote",
]
