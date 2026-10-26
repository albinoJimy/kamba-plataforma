"""Chaves virtuais e orcamentos por tenant (KAM-030, criterio 4).

    python infra/llm/chaves.py provisionar <tenant_id> <plano>
    python infra/llm/chaves.py orcamentos

Na Fase 0 isto corre **a mao**, e o bloco di-lo: «chave virtual criada no
provisioning; manualmente por *script* na Fase 0». O automatico e no evento
`tenant.approved` (TEN), que e o KAM-091.

## Porque e que a idempotencia e nossa e nao do proxy

Medido contra a imagem fixada (`docs/evidencia/KAM-030-litellm.md`):

* `POST /key/generate` com um `key_alias` novo → **200**;
* o **mesmo** corpo outra vez → **400** `"Key with alias '…' already exists.
  Unique key aliases across all keys are required."`

Ou seja, o `/key/generate` **nao e idempotente**, e o criterio 4 exige que criar
a chave de um tenant o seja. A idempotencia faz-se aqui, em tres passos:
procurar em `/key/list`, e depois `/key/update` (que aceita `key_alias`, medido:
200) ou `/key/generate`.

**E isto e tambem a razao de o mapeamento de erro do cliente nao ser pelo 400**:
o proxy usa o 400 para «alias repetido» e o **422** para orcamento esgotado. Um
cliente que mapeasse o 400 para `BUDGET_EXHAUSTED` dizia «sem orcamento» a um
erro de provisionamento — e nunca dizia nada quando o orcamento acabasse de
verdade. Ver `kamba_agr/llm/erros.py`.

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

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Callable, Final

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

#: O nome da chave virtual de um tenant. `tenant-<uuid>`, como o §13.1.
def alias_do_tenant(tenant_id: str) -> str:
    return f"tenant-{tenant_id}"


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
    #: diz quantas ha.
    POR_PAGINA = 500

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

    def gerar(self, corpo: dict[str, Any]) -> dict[str, Any]:
        estado, resposta = self._pedir(
            f"{self._url}/key/generate", "POST", self._chave, corpo
        )
        if estado != 200:
            raise ErroDeProvisionamento(
                f"/key/generate respondeu {estado}: {str(resposta)[:300]}"
            )
        return resposta if isinstance(resposta, dict) else {}

    def actualizar(self, corpo: dict[str, Any]) -> dict[str, Any]:
        estado, resposta = self._pedir(
            f"{self._url}/key/update", "POST", self._chave, corpo
        )
        if estado != 200:
            raise ErroDeProvisionamento(
                f"/key/update respondeu {estado}: {str(resposta)[:300]}"
            )
        return resposta if isinstance(resposta, dict) else {}


def provisionar(proxy: Proxy, tenant_id: str, plano: str, ambiente: Any = None) -> str:
    """Cria **ou actualiza** a chave virtual do tenant. Devolve `criada` ou `actualizada`.

    E isto que torna o criterio 4 idempotente: correr duas vezes com os mesmos
    argumentos deixa a mesma chave, com o mesmo `key_alias`, o mesmo orcamento e
    os mesmos metadados — e **nao** devolve 400.

    O que **nao** se repete e a chave em si: o `/key/update` nao a reemite, pelo
    que o valor que o cofre guarda continua valido. Reemitir a cada corrida
    obrigava a reescrever o segredo de todos os tenants por causa de um, e a
    escrita no cofre nem esta na porta (`ADR-L002` §6, lacuna do KAM-016).
    """
    alias = alias_do_tenant(tenant_id)
    orcamento = orcamento_do_plano(plano, ambiente)
    existente = proxy.procurar(alias)
    comum: dict[str, Any] = {
        "key_alias": alias,
        "models": list(MODELOS_DA_CHAVE),
        "max_budget": orcamento,
        "budget_duration": DURACAO,
        "metadata": {"tenant_id": tenant_id, "plano": plano},
    }
    if existente is None:
        try:
            proxy.gerar(comum)
        except ErroDeProvisionamento as excepcao:
            # **`check-then-act` nao e idempotente sob concorrencia**, e o
            # criterio 4 diz «e idempotente» sem qualificar: duas corridas ao
            # mesmo tempo — ou o KAM-091 a consumir `tenant.approved`
            # *at-least-once* — vem as duas `existente is None`, as duas chamam
            # `/key/generate`, e uma leva o 400 «already exists». Apanha-se esse
            # 400 **pelo texto que o proxy devolve** e cai-se para o
            # `actualizar`, que e o desfecho correcto: a chave existe e fica com
            # os valores desta corrida. Encontrado pela revisao adversarial
            # (achado 10).
            if "already exists" not in str(excepcao):
                raise
            proxy.actualizar(comum)
            return "actualizada"
        return "criada"
    proxy.actualizar(comum)
    return "actualizada"


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
            # O `tenant_id` **nao** vai para o `stdout` junto do valor da chave:
            # o `/key/generate` devolve a chave em claro e isto nunca a imprime.
            # Quem a guarda no cofre e quem corre o comando, do que o proxy
            # devolveu — e por isso o que sai daqui e so o desfecho.
            feito = provisionar(_proxy_do_ambiente(), args[1], args[2])
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
