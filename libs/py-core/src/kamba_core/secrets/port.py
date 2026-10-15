"""A porta `SecretProvider` do lado Python (KAM-010).

Espelho de `packages/core-ts/src/secrets/port.ts`. As duas portas tem de
significar o mesmo: o mesmo inventario (`ops/secrets-inventory.yaml`), as mesmas
referencias, o mesmo anel `[actual, anterior]` e as mesmas classes de erro. Se
divergirem, o mesmo cofre passa a ter dois contratos e o KAM-072 (rotacao) tem de
os rodar aos dois.

**Uma diferenca deliberada: aqui a porta e sincrona.** Do lado Node e
assincrona porque nao ha alternativa; aqui seria preciso arrastar um cliente
HTTP assincrono para dentro de `libs/py-core`, que nao tem dependencia nenhuma
por decisao do KAM-001. O AGR le segredos **ao arranque** (onde bloquear e o que
se quer) e, depois disso, o que precise de os reler fa-lo com
`asyncio.to_thread`. A razao esta escrita em `docs/adr/ADR-L002-injeccao-de-segredos.md` §5.

Tres regras atravessam este modulo:

1. nenhuma mensagem de erro contem um valor de segredo;
2. o que atravessa fronteiras e a referencia, nunca o valor (ver `SecretRef`);
3. "o cofre esta em baixo" e "este segredo nao existe" sao erros de classes
   diferentes, porque a reaccao certa e diferente.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

#: Referencia opaca a um segredo no cofre.
#:
#: E isto — e nunca o valor — que atravessa uma fronteira de persistencia, de
#: evento ou de log. O caso comum e a referencia ser o `id` do segredo no
#: inventario. Para familias com uma instancia por tenant, a referencia e o `id`
#: da familia seguido de um sufixo opaco que o cofre cunhou
#: (`meta_client_token/7f3cAb`).
#:
#: **Quem recebe uma referencia nao a interpreta.** O KAM-003 define a coluna que
#: guarda uma destas referencias (`tenant_channels.token_ref`); este ticket nao
#: define essa coluna nem o formato do sufixo, e de proposito.
SecretRef = str

#: Ambientes com projectos de cofre separados (`docs/tecnica/09` §6).
AMBIENTES = ("dev", "staging", "prod")

#: Forma aceite de uma referencia. O limite de comprimento nao e estetica: e o
#: que impede que um **valor** passado por engano onde devia ir uma referencia
#: apareca numa mensagem de erro.
_REF = re.compile(r"^[a-z][a-z0-9_]{2,63}(/[A-Za-z0-9._:-]{1,128})?$")


class SecretRefInvalidaError(ValueError):
    """A referencia pedida nao tem a forma de uma referencia."""

    def __init__(self, ref: object) -> None:
        # Comprimento e nao conteudo: se alguem passou um valor por engano, o
        # valor nao entra no log por causa desta mensagem.
        self.comprimento = len(ref) if isinstance(ref, str) else -1
        super().__init__(
            f"referencia de segredo invalida ({self.comprimento} caracteres); "
            "esperava <id> ou <id>/<instancia>, com <id> em snake_case"
        )


class SecretAusenteError(LookupError):
    """Um segredo obrigatorio nao existe no cofre."""

    def __init__(self, ref: SecretRef, provedor: str) -> None:
        self.ref = ref
        self.provedor = provedor
        super().__init__(f"segredo ausente: {ref} (provedor {provedor})")


class CofreInacessivelError(RuntimeError):
    """O cofre nao responde.

    Distinta de `SecretAusenteError` de proposito: esta tolera-se durante uma
    janela depois do arranque (ver `arranque.Secrets`), aquela nunca.
    """

    def __init__(self, provedor: str, motivo: str) -> None:
        self.provedor = provedor
        self.motivo = motivo
        super().__init__(f"cofre inacessivel (provedor {provedor}): {motivo}")


class AmbienteErradoError(RuntimeError):
    """O provedor esta configurado para outro ambiente."""

    def __init__(self, provedor: str, esperado: str, obtido: str) -> None:
        self.provedor = provedor
        self.esperado = esperado
        self.obtido = obtido
        super().__init__(
            f"credencial de cofre do ambiente {obtido!r} usada contra {esperado} "
            f"(provedor {provedor}); recusado"
        )


@runtime_checkable
class SecretProvider(Protocol):
    """A porta. So leitura.

    Cunhar uma referencia nova — escrever um segredo no cofre e receber de volta
    a referencia que a base de dados guarda — e o que o KAM-016 vai precisar, e
    **nao esta aqui**: nenhum servico do Piloto escreve no cofre, e uma porta de
    escrita sem consumidor e desenho especulativo. A lacuna esta declarada em
    `docs/adr/ADR-L002-injeccao-de-segredos.md` §6.
    """

    #: Nome curto da implementacao: `env`, `openbao-fake`, `doppler`.
    nome: str
    #: Ambiente para que este provedor esta configurado.
    ambiente: str

    def get(self, ref: SecretRef) -> str:
        """Devolve o valor actual.

        Levanta `SecretRefInvalidaError`, `SecretAusenteError` ou
        `CofreInacessivelError`.
        """
        ...

    def get_ring(self, ref: SecretRef) -> tuple[str, str | None]:
        """Devolve `(actual, anterior)`.

        `anterior` e `None` quando o segredo nunca foi rodado. Quem aceita as
        duas versoes — o GWY, na validacao de `X-Hub-Signature-256` (KAM-013) —
        tem de tratar `None` como "so ha uma", e nao como erro.
        """
        ...

    def versions(self, ref: SecretRef) -> tuple[str, ...]:
        """Identificadores das versoes vivas, da mais recente para a mais antiga.

        O conteudo de cada identificador e do provedor; a **ordem** e parte do
        contrato, e `versions()[0]` corresponde ao que `get()` devolve.
        """
        ...

    def health(self) -> None:
        """Nao devolve nada se o cofre esta acessivel; levanta
        `CofreInacessivelError` se nao.

        Nao le segredo nenhum: e a pergunta do arranque em `prod`, onde a
        resposta "nao sei" significa "nao arranques".
        """
        ...


def validar_ref(ref: object) -> SecretRef:
    """Valida a forma de uma referencia e devolve-a, para encadear."""
    if not isinstance(ref, str) or _REF.match(ref) is None:
        raise SecretRefInvalidaError(ref)
    return ref


def familia_da_ref(ref: SecretRef) -> str:
    """`id` da familia de uma referencia (a parte antes de `/`)."""
    return validar_ref(ref).split("/", 1)[0]


def e_ambiente(valor: object) -> bool:
    """`True` se `valor` e um dos tres ambientes canonicos."""
    return isinstance(valor, str) and valor in AMBIENTES
