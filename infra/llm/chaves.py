"""Chaves virtuais e orcamentos por tenant (KAM-030, criterio 4).

    python infra/llm/chaves.py provisionar <tenant_id> <plano>
    python infra/llm/chaves.py provisionar-screening
    python infra/llm/chaves.py orcamentos
    python infra/llm/chaves.py revogar <tenant_id>

Na Fase 0 isto corre **a mao**, e o bloco di-lo: «chave virtual criada no
provisioning; manualmente por *script* na Fase 0». O automatico e no evento
`tenant.approved` (TEN), que e o KAM-091.

## Porque e que a idempotencia e nossa e nao do proxy

Contra a imagem fixada, **com base de dados** (`docs/evidencia/KAM-247.md` §2,
e o §3 do `docs/evidencia/KAM-233.md`):

* `POST /key/generate` com um `key_alias` novo → **200** (medido no KAM-233 e no
  KAM-247);
* o **mesmo** corpo outra vez → **400** `"Key with alias '…' already exists.
  Unique key aliases across all keys are required."` (medido no KAM-247);
* `POST /key/update` com o `key_alias` e o `max_budget` → **200** (medido no
  KAM-247).

Esta nota dizia «medido» e apontava o `docs/evidencia/KAM-030-litellm.md`, que
nao traz nenhuma das medicoes (achado do KAM-233). **E sem base nao ha chave
nenhuma**: o `/key/generate` responde 500 (`DB not connected`). Desde o KAM-247 o
proxy de `staging` e `prod` tem a base `kamba_litellm` (decisao do fundador de
2026-11-23), e este *script* corre contra ele.

Ou seja, o `/key/generate` **nao e idempotente**, e o criterio 4 exige que criar
a chave de um tenant o seja. A idempotencia faz-se aqui: procurar em
`/key/list`, e depois `/key/update` ou `/key/generate` (ou, desde o KAM-250,
apagar e gerar, quando o cofre nao autentica a chave). O 400 de uma corrida
concorrente, pelo texto medido acima, repete o caminho **uma** vez, que compara
o resumo do valor do cofre e reemite se divergirem (`_garantir`).

**E isto e tambem a razao de o mapeamento de erro do cliente nao ser pelo 400**:
o proxy usa o 400 para «alias repetido» e o **422** para orcamento esgotado. Um
cliente que mapeasse o 400 para `BUDGET_EXHAUSTED` dizia «sem orcamento» a um
erro de provisionamento — e nunca dizia nada quando o orcamento acabasse de
verdade. Ver `kamba_agr/llm/erros.py`.

## O valor vai para o cofre, e nunca para o terminal (KAM-250)

Ate ao KAM-250 o valor que o proxy emite nao chegava a lado nenhum: o
`provisionar` nao o devolvia nem o imprimia, e o consumidor ficava sem chave. Pela
decisao do fundador de 2026-11-24 (opcao 1, bloco do KAM-250), as chaves virtuais
vivem num **projecto Doppler so delas** (`kamba_core.secrets.escrita`), e este
*script* escreve-as la com um *token* de escrita limitado a esse projecto
(`doppler_llm_chaves_escrita`). O AGR le-as do mesmo projecto, com um *token* so
de leitura.

**O valor gera-se aqui, e vai primeiro para o cofre.** O `/key/generate` aceita
o `key` no corpo e usa-o como chave (medido no KAM-250, `docs/evidencia/KAM-250.md`),
e o `token` que o `/key/list` devolve e o SHA-256 dela. Daqui sai a ordem, e a
repeticao segura do criterio 3:

1. le-se o cofre; sem valor, gera-se um e **grava-se antes** de falar com o proxy;
2. o proxy cria a chave **com esse valor**;
3. numa repeticao, o resumo do valor do cofre compara-se com o `token` da chave:
   se bater, o valor do cofre autentica, e so se actualiza o orcamento — **nao se
   reemite**; se a chave nao existir, cria-se com o valor que ja esta no cofre.

So se reemite quando o proxy tem uma chave que o valor do cofre **nao** autentica
(o cofre perdeu-a, ou a chave e anterior ao KAM-250): apaga-se e cria-se com o
valor do cofre. Uma queda a meio de qualquer passo converge na corrida seguinte, e
nenhum deles imprime ou regista o valor.

## O orcamento e um parametro, e nao se inventa

`docs/tecnica/02` §13.3: «Orcamento mensal da chave = 15% x mensalidade em USD».
A **mensalidade por plano nao esta definida** (o `docs/tecnica/10` nao a fixa), e
o bloco manda tratar isso como parametro a calibrar em H6. Por isso a mensalidade
vem do ambiente, por plano, e **sem ela o script recusa-se a correr** em vez de
usar um numero inventado: um orcamento com um valor a esmo e um tecto de custo
que ninguem decidiu.

    KAMBA_LLM_MENSALIDADE_USD_BASICO=...
    KAMBA_LLM_MENSALIDADE_USD_<PLANO>=...

## O alerta dos 80%

`docs/tecnica/02` §13.3 pede «alertas a 80%». O `spend` e o `max_budget` de cada
chave vem de `/key/list?return_full_object=true` (medido), que e a fonte certa:
quem **impoe** o orcamento e o proxy, e e dele que se le quanto falta. Somar a
nossa `dat.llm_call_log` daria outro numero — e, hoje, daria zero, porque o
`custo_usd` e nulo enquanto o modelo for `por_decidir` (KAM-040).

**Nao ha agendador nesta fase** (KAM-071), como no KAM-026 e no KAM-029: o
comando `orcamentos` existe e correr-se a horas e desse ticket. O que ele devolve
e um codigo de saida — 0 se nenhuma chave passou os 80%, 1 se alguma passou —
para que um `cron` o possa usar sem interpretar texto.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pathlib
import secrets
import sys
import urllib.error
import urllib.request
from typing import Any, Callable, Final, Protocol

# A porta de segredos vive em `libs/py-core`, que nao tem dependencias (ADR-L001):
# este *script* continua a correr fora de qualquer `.venv`, a partir do checkout.
_PY_CORE = pathlib.Path(__file__).resolve().parents[2] / "libs" / "py-core" / "src"
if str(_PY_CORE) not in sys.path:
    sys.path.insert(0, str(_PY_CORE))

from kamba_core.secrets import (  # noqa: E402
    PROJECTO_DAS_CHAVES_POR_OMISSAO,
    VARIAVEL_DO_PROJECTO,
    CofreInacessivelError,
    DopplerGravador,
    DopplerSecretProvider,
    EnvSecretProvider,
    SecretAusenteError,
    transporte_http_de_escrita,
    transporte_http_de_leitura,
)

#: A fraccao da mensalidade que vai para IA (`docs/tecnica/02` §13.3). ***Proposta***,
#: calibra-se em H6.
FRACCAO_DO_ORCAMENTO: Final = 0.15

#: O limiar do alerta (§13.3).
LIMIAR_DE_ALERTA: Final = 0.80

#: O ciclo do orcamento. O `budget_duration` do `/key/generate`.
DURACAO: Final = "30d"

#: Os grupos que uma chave de tenant pode chamar. **Nao inclui o
#: `kamba-vision` nem o `kamba-embed`**: aqueles correm no COM e no IDX
#: (`docs/tecnica/02` §13.2), nao no AGR, e uma chave de tenant que os pudesse
#: chamar dava a um turno de conversa acesso a dois papeis que nenhum no do
#: grafo usa.
#:
#: **O `kamba-chat-fallback2` tem de estar aqui**, e isso nao esta no exemplo do
#: §13.1 porque ali o *fallback* era uma segunda entrada do mesmo `model_name`.
#: Aqui sao **grupos distintos** (ver `tools/llm_config`), e o router comuta de
#: `kamba-chat` para `kamba-chat-fallback2`: sem o segundo nesta lista, uma
#: falha do primeiro fornecedor topava com a *allowlist* da propria chave e o
#: criterio 6 falhava em `staging` com toda a bateria verde — a medicao das 20
#: corridas foi feita com `Router(...)` em Python, sem chave virtual.
#: Encontrado pela revisao adversarial (achado 11).
#:
#: **Lista literal, de proposito**, e o preco esta escrito: derivar de
#: `llm/aliases.yaml` punha este *script* — que corre a mao, fora de qualquer
#: `.venv` — a depender do leitor de YAML de `tools/`. Em troca, ha um teste que
#: a confronta com os grupos que o gerador produz (`test_llm_chaves.py`).
MODELOS_DA_CHAVE: Final = ("kamba-router", "kamba-chat", "kamba-chat-fallback2")

#: **A chave do screening e da plataforma, e nao de um tenant** (KAM-195). A do
#: tenant nasce no `tenant.approved` e o screening do GOV corre antes dele — e a
#: aprovacao do KYC que espera pelo screening. Uma chave so, com `models` so o
#: `screening-nano`: quem a tiver nao alcanca nenhum papel de conversa. O AGR le
#: o valor do cofre (`litellm_screening_key`, `ops/secrets-inventory.yaml`).
#: O custo por tenant nao se perde: e a linha de `dat.llm_call_log`.
ALIAS_DA_CHAVE_DO_SCREENING: Final = "plataforma-screening"
MODELOS_DA_CHAVE_DO_SCREENING: Final = ("screening-nano",)

#: O orcamento mensal da chave do screening, em USD. **Sem valor, o comando
#: recusa-se**, pela razao da mensalidade: nao se inventa um tecto de custo. O
#: custo por decisao calibra-se com o modelo escolhido (KAM-040).
VAR_ORCAMENTO_DO_SCREENING: Final = "KAMBA_LLM_ORCAMENTO_USD_SCREENING"

#: O nome da chave virtual de um tenant. `tenant-<uuid>`, como o §13.1.
def alias_do_tenant(tenant_id: str) -> str:
    return f"tenant-{tenant_id}"


#: As referencias no cofre, como o `ops/secrets-inventory.yaml` as declara: a do
#: tenant leva a instancia (`instancias: tenant`), a do screening nao.
FAMILIA_DA_CHAVE_DO_TENANT: Final = "litellm_virtual_key"
REF_DA_CHAVE_DO_SCREENING: Final = "litellm_screening_key"


def ref_do_tenant(tenant_id: str) -> str:
    return f"{FAMILIA_DA_CHAVE_DO_TENANT}/{tenant_id}"


#: O *token* de escrita no projecto das chaves (decisao do fundador, KAM-250).
REF_DO_TOKEN_DE_ESCRITA: Final = "doppler_llm_chaves_escrita"

#: Octetos aleatorios do valor de uma chave. 32, como os *tokens* da casa.
OCTETOS_DA_CHAVE: Final = 32


def gerar_valor() -> str:
    """Um valor novo de chave virtual. O prefixo `sk-` e o que o proxy exige (medido)."""
    return "sk-" + secrets.token_urlsafe(OCTETOS_DA_CHAVE)


def resumo_da_chave(valor: str) -> str:
    """O `token` que o proxy guarda e lista para uma chave: o SHA-256 dela (medido).

    E isto que deixa confirmar que o valor do cofre autentica a chave **sem o
    mandar a lado nenhum**: compara-se com o `token` do `/key/list`.
    """
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


class Cofre(Protocol):
    """O que este *script* pede ao cofre: ler e gravar numa referencia fixa."""

    def ler(self, ref: str) -> str | None: ...

    def gravar(self, ref: str, valor: str) -> None: ...


VAR_PROXY: Final = "KAMBA_LLM_PROXY_URL"
VAR_MASTER_KEY: Final = "KAMBA_SECRET_LITELLM_MASTER_KEY"
PREFIXO_DA_MENSALIDADE: Final = "KAMBA_LLM_MENSALIDADE_USD_"


class ErroDeProvisionamento(RuntimeError):
    """O provisionamento nao pode continuar. A mensagem diz porque."""


def orcamento_do_plano(plano: str, ambiente: Any = None) -> float:
    """15% da mensalidade do plano, em USD. Levanta se o plano nao tiver valor."""
    ambiente = os.environ if ambiente is None else ambiente
    nome = PREFIXO_DA_MENSALIDADE + plano.upper()
    bruto = str(ambiente.get(nome, "")).strip()
    if not bruto:
        raise ErroDeProvisionamento(
            f"{nome} nao esta definida. A mensalidade por plano nao esta fixada em "
            "documento nenhum (`docs/tecnica/10`) e e parametro a calibrar em H6: "
            "um orcamento inventado e um tecto de custo que ninguem decidiu"
        )
    try:
        mensalidade = float(bruto)
    except ValueError as excepcao:
        raise ErroDeProvisionamento(f"{nome} nao e um numero") from excepcao
    if mensalidade <= 0:
        raise ErroDeProvisionamento(f"{nome} tem de ser positiva (lido {mensalidade})")
    return round(mensalidade * FRACCAO_DO_ORCAMENTO, 6)


def _pedir_http(
    url: str, metodo: str, chave: str, corpo: dict[str, Any] | None
) -> tuple[int, Any]:
    pedido = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode("utf-8") if corpo is not None else None,
        headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
        method=metodo,
    )
    try:
        with urllib.request.urlopen(pedido, timeout=30) as resposta:
            cru = resposta.read() or b"{}"
            return resposta.status, json.loads(cru)
    except urllib.error.HTTPError as erro:
        cru = erro.read()
        try:
            return erro.code, json.loads(cru or b"{}")
        except ValueError:
            return erro.code, cru[:400].decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        # **Rede nao e desfecho.** Sem isto, um proxy em baixo dava *traceback* e
        # exit 1 — que no contrato deste *script* significa «alguma chave passou
        # os 80%». Um `cron` que leia o codigo de saida passava a ler um alerta
        # onde houve uma falha de rede. Encontrado pela revisao adversarial
        # (achado 18).
        raise ErroDeProvisionamento(f"nao se alcancou o proxy em {url}: {erro}") from erro


class Proxy:
    """A parte da API de administracao do proxy que este script usa.

    `pedir` existe para as baterias; a omissao fala HTTP. So biblioteca padrao:
    isto corre em `infra/`, fora de qualquer `.venv` de servico.
    """

    def __init__(
        self,
        url: str,
        master_key: str,
        pedir: Callable[[str, str, str, dict[str, Any] | None], tuple[int, Any]] | None = None,
    ) -> None:
        if not master_key:
            raise ErroDeProvisionamento(
                f"{VAR_MASTER_KEY} nao esta definida: a *master key* vive no cofre "
                "(KAM-010) e sem ela a API de administracao recusa tudo"
            )
        self._url = url.rstrip("/")
        self._chave = master_key
        self._pedir = pedir or _pedir_http

    #: Quantas chaves se pedem por pagina. O proxy pagina, e o `total_count`
    #: diz quantas ha. **100, e nao 500**: a imagem fixada recusa `size` acima de
    #: 100 com **422** («Input should be less than or equal to 100»), medido no
    #: KAM-233 (`docs/evidencia/KAM-233.md` §3a). Com 500, o `listar` levantava em
    #: todas as chamadas, e com ele o `provisionar`, o `revogar` e o `orcamentos`.
    POR_PAGINA = 100

    def listar(self) -> list[dict[str, Any]]:
        """Todas as chaves, por paginas. **Levanta se nao as conseguir todas.**

        A primeira versao pedia `size=500`, lia `corpo["keys"]` e nao olhava
        para o `total_count`: com 501 chaves, o 501.o *tenant* ficava invisivel
        — o `provisionar` nao o encontrava, chamava `/key/generate` e levava o
        400 «already exists» numa execucao que devia ser idempotente, e o
        `orcamentos` simplesmente **nunca alertava** por ele, em silencio.
        Encontrado pela revisao adversarial (achado 9).
        """
        todas: list[dict[str, Any]] = []
        pagina = 1
        while True:
            estado, corpo = self._pedir(
                f"{self._url}/key/list?return_full_object=true"
                f"&size={self.POR_PAGINA}&page={pagina}",
                "GET",
                self._chave,
                None,
            )
            if estado != 200 or not isinstance(corpo, dict):
                raise ErroDeProvisionamento(
                    f"/key/list respondeu {estado}: {str(corpo)[:200]}"
                )
            desta = [k for k in (corpo.get("keys") or []) if isinstance(k, dict)]
            todas += desta
            total = corpo.get("total_count")
            if not desta or not isinstance(total, int) or len(todas) >= total:
                break
            pagina += 1
        total = corpo.get("total_count")
        if isinstance(total, int) and len(todas) != total:
            # Falha fechada: uma lista incompleta faz o `provisionar` gerar uma
            # chave que ja existe e o `orcamentos` calar-se sobre tenants reais.
            raise ErroDeProvisionamento(
                f"/key/list devolveu {len(todas)} chave(s) e diz ter {total}: "
                "uma lista incompleta faz o provisionamento gerar o que ja existe "
                "e o alerta de orcamento calar-se"
            )
        return todas

    def procurar(self, alias: str) -> dict[str, Any] | None:
        for chave in self.listar():
            if chave.get("key_alias") == alias:
                return chave
        return None

    def gerar(self, corpo: dict[str, Any]) -> None:
        """`/key/generate`. **Nao devolve a resposta**, que traz a chave em claro.

        Desde o KAM-250 o valor vai no corpo (`key`) e ja esta no cofre: quem chama
        nao precisa de nada do que o proxy devolve, e uma resposta que nao sai
        daqui nao pode ir parar a um *log*.

        **E a mensagem de erro nao cita o corpo**, ao contrario das outras rotas:
        medido no KAM-250, o 400 de uma chave mal formada ecoa os quatro primeiros
        e os quatro ultimos caracteres dela («Received: VLmi****al-4»). So se
        distingue o 400 do alias repetido, pelo texto medido, porque o `_garantir`
        decide por ele.
        """
        estado, resposta = self._pedir(
            f"{self._url}/key/generate", "POST", self._chave, corpo
        )
        if estado != 200:
            motivo = (
                "already exists"
                if "already exists" in str(resposta)
                else "corpo omitido, porque pode ecoar a chave"
            )
            raise ErroDeProvisionamento(f"/key/generate respondeu {estado}: {motivo}")

    def actualizar(self, corpo: dict[str, Any]) -> dict[str, Any]:
        estado, resposta = self._pedir(
            f"{self._url}/key/update", "POST", self._chave, corpo
        )
        if estado != 200:
            raise ErroDeProvisionamento(
                f"/key/update respondeu {estado}: {str(resposta)[:300]}"
            )
        return resposta if isinstance(resposta, dict) else {}


    def apagar(self, token: str) -> None:
        """`/key/delete` de uma chave, pelo `token` que o `/key/list` devolve.

        Medido na imagem fixada (KAM-233, `docs/evidencia/KAM-233.md` §3): o
        corpo `{"keys": [token]}`, com o *token* em resumo que o
        `/key/list?return_full_object=true` traz, da 200 e a chave deixa de
        autenticar; o mesmo pedido outra vez da **404**, e nao 200. Quem chama
        procura antes e confirma pela listagem, e nao pelo 200.
        """
        estado, resposta = self._pedir(
            f"{self._url}/key/delete", "POST", self._chave, {"keys": [token]}
        )
        if estado != 200:
            raise ErroDeProvisionamento(
                f"/key/delete respondeu {estado}: {str(resposta)[:300]}"
            )


def revogar(proxy: Proxy, tenant_id: str) -> str:
    """Revoga a chave virtual do tenant (KAM-218, o encerramento). `revogada` ou `inexistente`.

    E a revogacao da Fase 0, simetrica do `provisionar`: a chave de um tenant
    nasce **a mao** com o alias `tenant-<uuid>`, e nao fica no
    `provisioning_step` — pelo que a revogacao do encerramento
    (`packages/core-ts/src/offboarding/encerramento.ts`) a da por `sem_recurso`
    e ela continuava viva. O *runbook* do encerramento manda correr isto no D7.

    **Idempotente do lado de fora**: uma chave que ja nao existe e o sucesso de
    uma repeticao (`inexistente`). E **confirmada pela listagem**: um 200 do
    `/key/delete` com a chave ainda la levanta, em vez de se dar por revogada uma
    chave que continua a gastar o orcamento.
    """
    alias = alias_do_tenant(tenant_id)
    existente = proxy.procurar(alias)
    if existente is None:
        return "inexistente"
    token = existente.get("token")
    if not isinstance(token, str) or not token:
        raise ErroDeProvisionamento(
            f"a chave {alias} veio do /key/list sem o token: nao ha como a revogar"
        )
    proxy.apagar(token)
    if proxy.procurar(alias) is not None:
        raise ErroDeProvisionamento(
            f"o /key/delete respondeu 200 e a chave {alias} continua no /key/list"
        )
    return "revogada"


def _garantir(
    proxy: Proxy, cofre: Cofre, ref: str, comum: dict[str, Any], *, repetida: bool = False
) -> str:
    """Garante a chave `comum["key_alias"]` com o valor que esta no cofre em `ref`.

    Devolve `criada`, `actualizada` ou `reemitida`. A ordem esta no docstring do
    modulo; o que importa aqui e que **o cofre e escrito antes do proxy**, pelo
    que uma queda entre os dois deixa um valor no cofre sem chave — e a corrida
    seguinte cria a chave com esse valor, sem reemitir.
    """
    alias = comum["key_alias"]
    existente = proxy.procurar(alias)
    valor = cofre.ler(ref)
    if existente is not None:
        if valor is not None and existente.get("token") == resumo_da_chave(valor):
            # O criterio 3 do KAM-250: o valor do cofre autentica, e a chave nao
            # se reemite. O `/key/update` nao muda o valor.
            proxy.actualizar(comum)
            return "actualizada"
        # O proxy tem uma chave que o cofre nao autentica: ninguem a consegue
        # usar pelo procedimento escrito. Reemite-se, com o valor do cofre se o
        # houver.
        token = existente.get("token")
        if not isinstance(token, str) or not token:
            raise ErroDeProvisionamento(
                f"a chave {alias} veio do /key/list sem o token: nao ha como a reemitir"
            )
        proxy.apagar(token)
        desfecho = "reemitida"
    else:
        desfecho = "criada"
    if valor is None:
        valor = gerar_valor()
        cofre.gravar(ref, valor)
    try:
        proxy.gerar({**comum, "key": valor})
    except ErroDeProvisionamento as excepcao:
        # **`check-then-act` nao e idempotente sob concorrencia**: duas corridas
        # ao mesmo tempo — ou o KAM-091 a consumir `tenant.approved`
        # *at-least-once* — vem as duas a chave por criar, e uma leva o 400
        # «already exists» (o texto medido). Desde o KAM-250 nao basta cair para
        # o `/key/update`: a outra corrida pode ter gravado no cofre outro valor
        # depois desta. Repete-se o caminho inteiro **uma** vez, que compara o
        # resumo e reemite se o cofre e a chave divergirem.
        if "already exists" not in str(excepcao) or repetida:
            raise
        return _garantir(proxy, cofre, ref, comum, repetida=True)
    return desfecho


def provisionar(
    proxy: Proxy, tenant_id: str, plano: str, ambiente: Any = None, *, cofre: Cofre
) -> str:
    """Cria, actualiza ou reemite a chave virtual do tenant, com o valor no cofre.

    E isto que torna o criterio 4 do KAM-030 idempotente: correr duas vezes com
    os mesmos argumentos deixa a mesma chave, com o mesmo `key_alias`, o mesmo
    orcamento e os mesmos metadados — e **nao** devolve 400. E e isto que faz o
    criterio 3 do KAM-250: a segunda corrida nao reemite, porque o valor que esta
    em `litellm_virtual_key/<tenant_id>` continua a autenticar.
    """
    comum: dict[str, Any] = {
        "key_alias": alias_do_tenant(tenant_id),
        "models": list(MODELOS_DA_CHAVE),
        "max_budget": orcamento_do_plano(plano, ambiente),
        "budget_duration": DURACAO,
        "metadata": {"tenant_id": tenant_id, "plano": plano},
    }
    return _garantir(proxy, cofre, ref_do_tenant(tenant_id), comum)


def orcamento_do_screening(ambiente: Any = None) -> float:
    """O orcamento da chave do screening, do ambiente. Levanta se nao houver."""
    env = os.environ if ambiente is None else ambiente
    bruto = env.get(VAR_ORCAMENTO_DO_SCREENING)
    try:
        valor = float(bruto) if bruto else 0.0
    except ValueError:
        valor = 0.0
    # `math.isfinite` e nao so `> 0`: `float("nan") <= 0` e falso, e um `nan` ou
    # um `inf` passavam como orcamento (achado 7 da revisao adversarial).
    if not math.isfinite(valor) or valor <= 0:
        raise ErroDeProvisionamento(
            f"{VAR_ORCAMENTO_DO_SCREENING} nao esta definido como numero positivo: "
            "o orcamento da chave do screening nao se inventa (KAM-195)"
        )
    return valor


def provisionar_screening(proxy: Proxy, ambiente: Any = None, *, cofre: Cofre) -> str:
    """Cria, actualiza ou reemite a chave da plataforma do screening (KAM-195).

    O mesmo desenho do `provisionar`, com o valor em `litellm_screening_key`.
    """
    comum: dict[str, Any] = {
        "key_alias": ALIAS_DA_CHAVE_DO_SCREENING,
        "models": list(MODELOS_DA_CHAVE_DO_SCREENING),
        "max_budget": orcamento_do_screening(ambiente),
        "budget_duration": DURACAO,
        "metadata": {"papel": "screening"},
    }
    return _garantir(proxy, cofre, REF_DA_CHAVE_DO_SCREENING, comum)


def orcamentos(proxy: Proxy) -> list[tuple[str, float, float]]:
    """As chaves que passaram os 80% do orcamento: `(alias, gasto, tecto)`.

    Uma chave com `max_budget` nulo ou zero **nao** entra: sem tecto nao ha
    fraccao, e um `max_budget: 0` e uma chave desligada de proposito — contar 0/0
    como «100% gasto» enchia o alerta de ruido por uma divisao impossivel.
    """
    acima: list[tuple[str, float, float]] = []
    for chave in proxy.listar():
        tecto = chave.get("max_budget")
        gasto = chave.get("spend") or 0.0
        if not isinstance(tecto, (int, float)) or tecto <= 0:
            continue
        if float(gasto) / float(tecto) >= LIMIAR_DE_ALERTA:
            acima.append((str(chave.get("key_alias") or "?"), float(gasto), float(tecto)))
    return sorted(acima)


def _proxy_do_ambiente() -> Proxy:
    return Proxy(
        os.environ.get(VAR_PROXY, "http://127.0.0.1:4000"),
        os.environ.get(VAR_MASTER_KEY, ""),
    )


class CofreDoppler:
    """O `Cofre` sobre o projecto Doppler das chaves virtuais (KAM-250).

    Le e grava com o **mesmo** *token*, o de escrita, que no Doppler tambem le
    (`A_CONFIRMAR_ESCRITA["limite_do_token"]`). A leitura nao guarda descarga
    (`ttl_descarga_s=0`): uma leitura depois de uma escrita tem de ver a escrita.
    """

    def __init__(self, ambiente: str, projecto: str, token: str) -> None:
        self._leitor = DopplerSecretProvider(
            ambiente, projecto, ambiente, token, transporte_http_de_leitura,
            ttl_descarga_s=0.0,
        )
        self._gravador = DopplerGravador(
            ambiente, projecto, ambiente, token, transporte_http_de_escrita
        )

    def ler(self, ref: str) -> str | None:
        try:
            return self._leitor.get(ref)
        except SecretAusenteError:
            return None
        except CofreInacessivelError as excepcao:
            # As mensagens do adaptador nunca levam valores (regra 1 da porta).
            raise ErroDeProvisionamento(str(excepcao)) from None

    def gravar(self, ref: str, valor: str) -> None:
        try:
            self._gravador.gravar(ref, valor)
        except CofreInacessivelError as excepcao:
            raise ErroDeProvisionamento(str(excepcao)) from None


def _cofre_do_ambiente() -> Cofre:
    """O cofre das chaves, do ambiente. **Levanta antes de se falar com o proxy.**

    A ordem importa: sem cofre, uma chave criada no proxy tinha um valor que nao
    ficava em lado nenhum — e o defeito que o KAM-250 fecha.
    """
    ambiente = os.environ.get("KAMBA_ENV", "").strip()
    if not ambiente:
        raise ErroDeProvisionamento(
            "KAMBA_ENV nao esta definido: o cofre das chaves tem uma configuracao "
            "por ambiente, e o valor nao se grava no ambiente errado"
        )
    try:
        acesso = EnvSecretProvider(ambiente).get(REF_DO_TOKEN_DE_ESCRITA)
    except (SecretAusenteError, ValueError) as excepcao:
        raise ErroDeProvisionamento(
            f"sem o {REF_DO_TOKEN_DE_ESCRITA} no ambiente nao ha onde guardar a "
            "chave, e uma chave sem cofre e uma chave perdida (KAM-250)"
        ) from excepcao
    projecto = os.environ.get(VARIAVEL_DO_PROJECTO, PROJECTO_DAS_CHAVES_POR_OMISSAO)
    try:
        return CofreDoppler(ambiente, projecto, acesso)
    except Exception as excepcao:  # noqa: BLE001 - as do adaptador nao levam valores
        raise ErroDeProvisionamento(f"cofre das chaves: {excepcao}") from None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__.split("\n\n")[1].strip(), file=sys.stderr)
        return 2
    try:
        if args[0] == "provisionar":
            if len(args) != 3:
                print("uso: provisionar <tenant_id> <plano>", file=sys.stderr)
                return 2
            # O valor da chave **nunca** sai daqui: vai para o cofre
            # (`litellm_virtual_key/<tenant_id>`) antes de ir para o proxy, e o
            # que se imprime e so o desfecho e o alias (KAM-250). O cofre monta-se
            # primeiro, para que a falta dele recuse antes de o proxy criar nada.
            cofre = _cofre_do_ambiente()
            feito = provisionar(_proxy_do_ambiente(), args[1], args[2], cofre=cofre)
            print(f"chave virtual {feito}: {alias_do_tenant(args[1])}")
            return 0
        if args[0] == "provisionar-screening":
            if len(args) != 1:
                print("uso: provisionar-screening", file=sys.stderr)
                return 2
            cofre = _cofre_do_ambiente()
            feito = provisionar_screening(_proxy_do_ambiente(), cofre=cofre)
            print(f"chave virtual {feito}: {ALIAS_DA_CHAVE_DO_SCREENING}")
            return 0
        if args[0] == "revogar":
            if len(args) != 2:
                print("uso: revogar <tenant_id>", file=sys.stderr)
                return 2
            feito = revogar(_proxy_do_ambiente(), args[1])
            print(f"chave virtual {feito}: {alias_do_tenant(args[1])}")
            return 0
        if args[0] == "orcamentos":
            acima = orcamentos(_proxy_do_ambiente())
            for alias, gasto, tecto in acima:
                print(f"ALERTA {alias}: {gasto:.6f} de {tecto:.6f} USD ({gasto / tecto:.0%})")
            print(f"{len(acima)} chave(s) acima de {LIMIAR_DE_ALERTA:.0%}")
            return 1 if acima else 0
    except ErroDeProvisionamento as excepcao:
        print(f"chaves: {excepcao}", file=sys.stderr)
        return 2
    print(f"comando desconhecido: {args[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
