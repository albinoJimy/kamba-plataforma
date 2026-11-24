"""A entrega do conteudo ao dono, e a publicacao que nao existe (KAM-122, criterio 7; D13).

    SocialPublisher.deliver(pedido) -> Entrega   o que o dono recebe para publicar a mao
    SocialPublisher.publish(pedido)              lanca NotEnabled, sempre

A publicacao por API exige o Advanced Access da Meta (App Review e Business
Verification), sem prazo oficial, e esta **Diferida** (D13): o gatilho e o App
Review aprovado e pelo menos tres PME com Pagina ou conta profissional. Ate la
**so a `ManualDelivery` existe**, e o `publish()` dela lanca `NotEnabled` — nao
devolve falso nem regista um aviso: uma chamada a publicar e um defeito de
quem a fez, e tem de rebentar no ensaio.

Um `FacebookPagePublisher` ou um `InstagramPublisher` sao do dia do gatilho, e
consomem o `content.approved`. O ensaio de CI do `lint_arch` (`redes_sociais`)
garante que ate la nao ha caminho, permissao nem segredo de rede no
repositorio.

## O que a entrega leva

A arte como imagem, a legenda como texto copiavel e a nota do rotulo de IA: a
responsabilidade de marcar o conteudo como gerado por IA ao publicar e do dono
(o `E5`), e a entrega lembra-lha sempre que o item tem `is_ai_generated`. Na
primeira entrega a um tenant vai tambem a mensagem dos termos (sem garantia de
exclusividade das imagens geradas, *a confirmar por parecer*).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, NoReturn, Protocol

#: A nota do rotulo de IA (criterio 8). Sem digitos: vai ao `send` sem validador.
NOTA_DO_ROTULO_DE_IA: Final = (
    "Este conteudo foi gerado com inteligencia artificial. Ao publicar, active o rotulo de IA "
    "da rede social (por exemplo, a opcao de conteudo gerado por IA do Instagram ou do Facebook)."
)

#: Os termos da primeira entrega (criterio 9). *A confirmar por parecer* (Lei 15/14, INDICIO).
TERMOS_DA_PRIMEIRA_ENTREGA: Final = (
    "Antes da primeira publicacao: as imagens geradas por inteligencia artificial podem nao ter "
    "protecao de direitos de autor e nao sao exclusivas da sua loja. O texto e os dados sao seus."
)


class NotEnabled(RuntimeError):
    """A publicacao automatica nao esta activa (D13). Nunca e apanhada para seguir em frente."""


@dataclass(frozen=True)
class PedidoDeEntrega:
    """O que se entrega: um item **aprovado**, com a legenda e a arte que o dono aprovou."""

    content_item_id: str
    tenant_id: str
    legenda: str
    arte_ref: str | None
    is_ai_generated: bool
    primeira_entrega: bool


@dataclass(frozen=True)
class Entrega:
    """As partes da mensagem de entrega, pela ordem em que o dono as recebe."""

    content_item_id: str
    arte_ref: str | None
    legenda: str
    nota: str | None
    termos: str | None


class SocialPublisher(Protocol):
    def deliver(self, pedido: PedidoDeEntrega) -> Entrega: ...

    def publish(self, pedido: PedidoDeEntrega) -> NoReturn: ...


class ManualDelivery:
    """A unica implementacao: entrega ao dono, que publica a mao."""

    nome: Final = "manual"

    def deliver(self, pedido: PedidoDeEntrega) -> Entrega:
        if not pedido.legenda:
            raise ValueError("a entrega precisa da legenda aprovada")
        return Entrega(
            content_item_id=pedido.content_item_id,
            arte_ref=pedido.arte_ref,
            legenda=pedido.legenda,
            nota=NOTA_DO_ROTULO_DE_IA if pedido.is_ai_generated else None,
            termos=TERMOS_DA_PRIMEIRA_ENTREGA if pedido.primeira_entrega else None,
        )

    def publish(self, pedido: PedidoDeEntrega) -> NoReturn:
        raise NotEnabled("a publicacao em redes sociais esta diferida (D13): o dono publica a mao")
