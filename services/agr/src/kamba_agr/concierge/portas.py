"""As portas do modo concierge (KAM-114).

Sem dependencias para dentro do AGR, pela razao do `handoff/portas.py`: e o que
permite ao `verticais/vendedor/nos.py` importar daqui sem o caminho inverso
existir.

## O que acontece quando o HND nao aceita o rascunho, e porque nao se melhora

O `handoff_prepare` do KAM-034, quando o provedor esta em baixo, **degrada e
manda uma mensagem estatica** ao cliente (a linha 37 da tabela de arestas). Aqui
nao se pode fazer o mesmo, e a razao e o criterio 1: «0 mensagens ao cliente sem
decisao `aprovado` ou `editado` registada». Uma mensagem de degradacao e uma
mensagem ao cliente, pelo que manda-la era violar o criterio que este ticket
existe para impor.

O que fica, e e o significado honesto de *fail-closed* aqui:

1. a linha fica em `platform.draft_decisions` como `pendente` — ha **registo** da
   tentativa, e e por isso que o `publicar` falhado nao impede a insercao;
2. conta-se (`agr_draft_indisponivel_total`);
3. o grafo interrompe de qualquer maneira, e a varredura dos prazos marca
   `expirado` as 24 h e retoma-o — exactamente como o `timeout` do handoff;
4. **o cliente nao recebe nada.**

O ponto 4 e uma perda real e escreve-se em vez de se descobrir. Nao se
«resolve» com uma mensagem estatica porque isso e precisamente a barreira a
abrir-se, e a regra da casa e que *minimo* nunca e retirar uma barreira. Quem a
quiser fechar por outro lado — um texto pre-aprovado por *tenant*, que seria uma
decisao ja tomada e nao uma mensagem sem aprovacao — decide-o com o Responsavel
de Produto, que e o mesmo credor a quem o criterio 4 devolve o «bloquear em vez
de sinalizar».
"""

from __future__ import annotations

from typing import Protocol


class RascunhoIndisponivel(RuntimeError):
    """O HND nao aceitou publicar o rascunho ao operador.

    O que o grafo faz com ela esta na nota do modulo: registo, contagem,
    `interrupt()` e **nenhuma** mensagem ao cliente.
    """


class ConciergeSemServicoError(RuntimeError):
    """A politica esta activa e o `ServicoDeRascunho` nao esta ligado.

    **Levanta, e nao interrompe**, e a diferenca nao e de estilo. Sem servico
    nao se grava linha nenhuma, e um `interrupt()` sem linha e uma conversa
    **morta em definitivo**, nao por 24 h:

    * a varredura dos prazos lista a `platform.draft_decisions` e **nunca**
      encontra este rascunho, logo nunca o expira nem retoma o grafo;
    * uma chamada a `/internal/draft-decision` nao casa o CAS, o `_classificar`
      devolve `recusado` e a rota responde **404** — ninguem o pode decidir;
    * e a invariante do §11 proibe invocar o grafo com *input* novo num *thread*
      com `interrupt` pendente, pelo que a conversa deixa de aceitar mensagens.

    Levantar faz o turno falhar, a mensagem fica na fila e o alerta diz que ha
    uma configuracao errada — que e o que o `versao_lida` do KAM-026 faz para o
    estado vindo do futuro, e pela mesma razao. **Nao sai mensagem nenhuma nos
    dois casos**; o que muda e que um deixa a conversa recuperavel.

    A primeira versao deste ticket tratava a falta de servico como «a omissao
    honesta» e interrompia de qualquer maneira, com um comentario a dizer que
    era seguro porque nao enviava. Era meia verdade, e a metade que faltava era
    esta. Apanhado pela revisao adversarial.
    """


class PortaDeRascunho(Protocol):
    """O `postDraft` do `HandoffProvider` (`docs/tecnica/01` §11.1, extensao).

    **Uma operacao e nao duas.** O bloco do ticket nomeia «`postDraft` e evento
    de decisao»; o evento de decisao **nao** e uma operacao desta porta — e um
    *callback* que entra pelo HND e sai em `POST /internal/draft-decision`, isto
    e, atravessa a fronteira no sentido contrario. Declara-lo aqui dava uma
    porta com um metodo que o AGR nunca chama, que e o argumento que o
    `PortaDoProvedor` do KAM-034 escreveu para as cinco operacoes que nao sao o
    `abrir`.

    **Idempotente por `draft_id`**, pela mesma propriedade que o `abrir` do
    handoff compra com `ON CONFLICT`: o no repete e o operador ve **um** pedido
    de aprovacao. Sem isto, um *worker* que caia entre a publicacao e o
    *checkpoint* mostrava o mesmo rascunho duas vezes e o operador aprovava duas
    — e o `{draft_id}:send` do Outbound salvava o envio, mas o painel contava
    duas decisoes para um turno.

    **Recebe o texto e nao o estado.** E a licao que a revisao adversarial do
    KAM-031 mediu no `_resumo` do handoff: a janela de mensagens atravessava
    para o HND num campo que o §6.4 nao cobre. Aqui o texto do rascunho **tem**
    de atravessar — e o que o operador le —, mas o resto do estado nao, e o que
    atravessa e so isto.

    Levanta `RascunhoIndisponivel` quando o provedor nao aceitou.
    """

    def publicar(
        self,
        *,
        draft_id: str,
        tenant_id: str,
        contact_id: str,
        conversation_id: str,
        texto: str,
        motivos: tuple[str, ...],
    ) -> str: ...


__all__ = [
    "ConciergeSemServicoError",
    "PortaDeRascunho",
    "RascunhoIndisponivel",
]
