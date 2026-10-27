"""`kamba_agr.eventos` — as verticais acordam por evento (KAM-038).

«As verticais nao se chamam entre si: subscrevem eventos do EVT» (ADR-009). O
AGR acorda quando ha algo a fazer: um pagamento confirmado, um pedido que
expirou, *stock* baixo, uma marcacao criada, um lembrete a vencer.

    entrega --> envelope --> rota (tipo, versao) --> entitlement
            --> tranca da conversa --> consumir (marca + efeito) --> notificacao

Os modulos, e o que cada um decide:

| Modulo | Decide |
|---|---|
| `envelope` | o que e um envelope v1 e o que se recusa (`docs/tecnica/06` §4) |
| `subscricoes` | que consumidores existem, a partir de `registry/*.yaml` |
| `desfechos` | as tres listas fechadas que sao etiqueta e coluna |
| `handlers` | o que cada tipo manda dizer, e a quem (`03` §12) |
| `turnos` | a tranca da conversa e quem tem a palavra (criterio 5) |
| `notificacao` | as duas saidas — Outbound e HND — e a chave do §6.3 |
| `dlq` | quando se abre entrada, e o que **nao** se guarda nela |
| `consumo` | a entrega inteira, do corpo ao efeito |
| `consultas` | o SQL, em constantes, que a *suite* do *gate* 8 corre |

**O nome dos modulos e portugues**, como o resto do servico (`turno.py`,
`trancas.py`, `admissao.py`): os `kamba/events/{subscribe,handlers,envelope,
turns}.py` dos *Detalhes Tecnicos* do bloco sao o nome do documento e nao o do
codigo — o pacote chama-se `kamba_agr` e o KAM-025 ja decidiu que o que e so do
AGR vive nele.

**As garantias de entrega do BullMQ sao NAO VERIFICADAS** (L6, R9 do epic), e
nada aqui assenta nelas: o que cobre o risco sao *handlers* idempotentes por
`evento.id` (a transaccao do KAM-006), a DLQ e o reprocessamento.
"""

from .consumo import (
    CAMPOS_DA_ENTREGA,
    ConsumidorDeEventos,
    DesfechoDaEntrega,
    Entrega,
    EntregaInvalidaError,
    EntregaPorRepetir,
    ler_entrega,
)
from .desfechos import (
    DESFECHOS_DA_NOTIFICACAO,
    DESFECHOS_DO_EVENTO,
    MOTIVOS_DA_DLQ,
)
from .dlq import FilaDeMortos
from .envelope import CAMPOS_DO_ENVELOPE, Envelope, EnvelopeInvalidoError, ler_envelope
from .entitlement import LeitorDeEntitlements
from .handlers import (
    ContactoPorResolver,
    PortaDeContacto,
    SemHandlerError,
    exigir_handlers,
)
from .notificacao import (
    Notificacao,
    Notificador,
    PortaDeAvisoAoDono,
    PortaDeNotificacao,
)
from .subscricoes import (
    Consumidor,
    SubscricoesInvalidasError,
    consumidores,
    nome_do_consumidor,
)
from .subscricoes import nomes as nomes_dos_consumidores
from .turnos import Conversa, LeitorDeConversas

__all__ = [
    "CAMPOS_DA_ENTREGA",
    "CAMPOS_DO_ENVELOPE",
    "DESFECHOS_DA_NOTIFICACAO",
    "DESFECHOS_DO_EVENTO",
    "MOTIVOS_DA_DLQ",
    "Consumidor",
    "ConsumidorDeEventos",
    "ContactoPorResolver",
    "Conversa",
    "DesfechoDaEntrega",
    "Entrega",
    "EntregaInvalidaError",
    "EntregaPorRepetir",
    "Envelope",
    "EnvelopeInvalidoError",
    "FilaDeMortos",
    "LeitorDeConversas",
    "LeitorDeEntitlements",
    "SemHandlerError",
    "nomes_dos_consumidores",
    "Notificacao",
    "Notificador",
    "PortaDeAvisoAoDono",
    "PortaDeContacto",
    "PortaDeNotificacao",
    "SubscricoesInvalidasError",
    "consumidores",
    "exigir_handlers",
    "ler_entrega",
    "ler_envelope",
    "nome_do_consumidor",
]
