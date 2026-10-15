"""`OpenBaoFakeProvider` — o *fake* de OpenBao (KAM-010).

Espelho de `packages/core-ts/src/secrets/openbao-fake.ts`, com a mesma ressalva
e pela mesma razao:

E um ***fake* da porta**, com a semantica de versoes do KV v2 — cada referencia
tem uma lista de versoes numeradas a partir de `1`, a maior e a actual, a
anterior e a penultima. **Nao** e um *mock* do protocolo: nao imita caminhos,
codigos de estado nem a forma do JSON. A forma exacta das respostas da API do
OpenBao e **NAO VERIFICADO** nesta sessao (sem rede e sem cofre instalado);
confirma-se em `openbao.org/api-docs/secret/kv/kv-v2/` antes de alguem escrever
o adaptador verdadeiro, que e trabalho dos Clusters e nao deste ticket
(`docs/tecnica/08` §5).

O que o *fake* **sim** reproduz, porque e o que o nosso codigo tem de aguentar:
um cofre **selado**. Um OpenBao selado responde, mas nao serve segredos — e o
estado em que um reinicio do cofre deixa o cluster ate alguem o destrancar, e e
a razao pela qual `CofreInacessivelError` existe como classe separada de
`SecretAusenteError`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .port import (
    CofreInacessivelError,
    SecretAusenteError,
    SecretRef,
    validar_ref,
)


class OpenBaoFakeProvider:
    """*Fake* de OpenBao com semantica de versoes do KV v2."""

    def __init__(
        self,
        ambiente: str,
        dados: Mapping[str, Sequence[str]] | None = None,
        selado: bool = False,
    ) -> None:
        self.nome = "openbao-fake"
        self.ambiente = ambiente
        self._selado = selado
        self._dados: dict[str, list[str]] = {}
        for ref, versoes in (dados or {}).items():
            if len(versoes) == 0:
                continue
            # Da mais antiga para a mais recente.
            self._dados[validar_ref(ref)] = list(versoes)

    def selar(self) -> None:
        """Sela o cofre: tudo passa a `CofreInacessivelError` ate `destrancar()`."""
        self._selado = True

    def destrancar(self) -> None:
        """Destranca o cofre."""
        self._selado = False

    def escrever(self, ref: SecretRef, valor: str) -> str:
        """Escreve uma versao nova e devolve o seu identificador.

        Existe para os testes montarem o cenario de rotacao. **A porta nao tem
        escrita** — ver `port.SecretProvider`.
        """
        chave = validar_ref(ref)
        versoes = self._dados.setdefault(chave, [])
        versoes.append(valor)
        return str(len(versoes))

    def health(self) -> None:
        if self._selado:
            raise CofreInacessivelError(self.nome, "cofre selado")

    def get(self, ref: SecretRef) -> str:
        return self._versoes(ref)[-1]

    def get_ring(self, ref: SecretRef) -> tuple[str, str | None]:
        versoes = self._versoes(ref)
        return versoes[-1], (versoes[-2] if len(versoes) > 1 else None)

    def versions(self, ref: SecretRef) -> tuple[str, ...]:
        total = len(self._versoes(ref))
        # Do mais recente para o mais antigo, como a porta exige.
        return tuple(str(n) for n in range(total, 0, -1))

    def _versoes(self, ref: SecretRef) -> list[str]:
        self.health()
        chave = validar_ref(ref)
        versoes = self._dados.get(chave)
        if not versoes:
            raise SecretAusenteError(chave, self.nome)
        return versoes


__all__ = ["OpenBaoFakeProvider"]
