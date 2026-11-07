"""O *gate* de go-live de um tenant (KAM-069, criterio 8).

«O *gate* de go-live recusa `onboarding` -> `ativo` em `prod` se faltar destino
autorizado para algum destino activo do tenant, o DPA aceite (KAM-090) ou a
referencia do mapa de tratamentos; ambientes sinteticos usam um ficheiro de
configuracao que `prod` nao carrega (verificacao no arranque).»

## Entrega-se com o chamador nomeado e nao ligada, e isso e medicao e nao atalho

**Ninguem escreve a transicao `onboarding` -> `ativo` hoje.** Medido: o passo 1
da saga de provisioning (`packages/core-ts/src/provisioning/passos.ts`) faz o
`INSERT` na `platform.tenants` com o estado inicial, e nenhum codigo do
repositorio o move de `onboarding` — nem o `qualidade/` do KAM-021, que o diz por
extenso («**nao escreve `tenants.estado`**»). O dicionario §3.2 retirou o `estado`
do `kamba_app` na emenda 1.18 precisamente porque «o sujeito de uma condicao nao
pode ser quem a retira».

Logo a barreira existe, esta provada e **nao tem chamador**. Credor: **KAM-110**
(activacao de tenant). Entregar a funcao com o credor escrito e o padrao desta
linha de tickets — o KAM-028 deixou o passo 5 para o KAM-029, o KAM-030 deixou
esta porta para este ticket — e a alternativa era nao entregar barreira nenhuma
para uma transicao que, quando alguem a escrever, nao tera onde a consultar.

## A decisao e pura, e ha duas leitoras

O `avaliar_go_live` recebe a lista de destinos activos, o estado do DPA e a referencia do
mapa, e devolve as **faltas**. Nao vai a base, nao le o ambiente, nao levanta.
Quem lhe da os destinos sao duas funcoes diferentes:

* `destinos_do_tenant`, que le `platform.tenant_destinations` (`prod` e
  `staging` com base);
* `ConfiguracaoSintetica.ler`, que le o ficheiro dos ambientes sinteticos.

Uma decisao com duas fontes e **uma** regra; duas regras era como as duas fontes
divergiam sem ninguem dar por isso.

## O ficheiro dos sinteticos, e porque e que `prod` o recusa no arranque

Um ambiente sintetico nao tem autorizacoes da APD, nao tem DPA assinado por PME
nenhuma e nao tem mapa aprovado — e tem de poder activar tenants para correr os
ensaios. O ficheiro declara essas tres coisas, e por isso **e uma porta aberta**:
quem o carregasse em `prod` activava tenants sem nada do que o requisito 4 e o
requisito 9 de `E3` exigem.

A defesa nao e «`prod` nao o carrega»: e **`prod` recusa arrancar se ele estiver
declarado**. A diferenca e a que separa uma convencao de uma barreira — um
`if ambiente != 'prod'` espalhado pelo codigo falha no sitio que alguem esquecer,
e uma variavel de ambiente herdada de um `.env` copiado e exactamente o engano
que acontece. E a mesma escolha do `exigir_envio_real` do `sms/fornecedor.ts` e
do `arrancar` do `storage/config.ts`: a recusa e no arranque, onde se ve.

## O que este modulo nao decide

Se o DPA existe. **Nao existe** — e o KAM-090, e o `GoLive_Gate.md` do KAM-105
registra-o como «**nao** redigido». O *gate* trata a ausencia como falta, que e o
lado seguro e e o que o requisito 4 manda («tenant sem DPA nao activa»). Nem o
conteudo do mapa de tratamentos: aqui exige-se a **referencia** e, quando quem
chama a souber, que ela seja a do mapa vivo.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .porta import TransferenciaNegada, estado_bloqueia

#: O ambiente em que as faltas deixam de ser avisos e passam a recusa.
#:
#: **O mesmo nome** que o `AMBIENTE_BLOQUEANTE` do `sms/fornecedor.ts` e do
#: `avisos/fornecedor.ts` e que o `AMBIENTE_PROD` do `llm/destinos.py`: tres
#: modulos a chamar `prod` ao mesmo ambiente, e um quarto a chamar-lhe outra
#: coisa era a divergencia mais barata de evitar deste ficheiro.
AMBIENTE_PROD: Final = "prod"

#: A variavel que aponta para o ficheiro dos ambientes sinteticos.
#:
#: Nao e um segredo, e nao guarda nenhum: o ficheiro declara pares
#: (fornecedor, finalidade) e duas afirmacoes, e nada disso e credencial.
VARIAVEL_SINTETICOS: Final = "KAMBA_GOLIVE_SINTETICO"

#: A forma da referencia do mapa de tratamentos: `<major>.<n>+<12 hex>`.
#:
#: E a que o gerador produz (dicionario §3.48), e exige-se a forma e nao so a
#: presenca porque uma referencia como `v1` ou `ultimo` nao identifica conteudo
#: nenhum — e o criterio 9 pede que «alterar uma linha altere a versao».
FORMA_DO_MAPA: Final = re.compile(r"^[0-9]+\.[0-9]+\+[0-9a-f]{12}$")


@dataclass(frozen=True)
class DestinoActivo:
    """Um par (fornecedor, finalidade) que o tenant tem registado, e o estado."""

    provider: str
    purpose: str
    status: str
    tem_apd_ref: bool

    @property
    def autorizado(self) -> bool:
        return not estado_bloqueia(self.status) and self.tem_apd_ref


@dataclass(frozen=True)
class Falta:
    """O que impede o go-live. **Leva o que falta, nunca o valor que falta.**"""

    #: `destino`, `dpa` ou `mapa`. Fixo em tres: o criterio nomeia tres coisas.
    especie: str
    #: Uma frase accionavel, com o credor quando ele e um ticket.
    detalhe: str

    def __str__(self) -> str:
        return f"{self.especie}: {self.detalhe}"


class GoLiveNegado(RuntimeError):
    """O tenant nao passa a `ativo`. Leva **todas** as faltas, nao a primeira.

    Parar na primeira obrigava quem activa um tenant a resolver uma, voltar a
    correr, descobrir a seguinte — e o criterio nomeia tres condicoes que podem
    faltar ao mesmo tempo. E a mesma razao do `DeclaracaoInvalidaError` do
    `sms/fornecedor.ts`, que junta os problemas num `join`.
    """

    def __init__(self, tenant_id: str, faltas: Sequence[Falta]) -> None:
        self.faltas = tuple(faltas)
        super().__init__(
            f"o tenant {tenant_id} nao passa a `ativo` em `{AMBIENTE_PROD}`: "
            + "; ".join(str(f) for f in self.faltas)
            + ". Nenhum dado pessoal de producao entra sem destino autorizado, "
            "DPA aceite e mapa de tratamentos (ADR-008, E3 requisitos 4 e 9, "
            "KAM-069)"
        )


class ConfiguracaoDeProdInvalida(RuntimeError):
    """`prod` com o ficheiro dos sinteticos declarado. **Recusa no arranque.**"""

    def __init__(self) -> None:
        super().__init__(
            f"`{VARIAVEL_SINTETICOS}` esta definida com "
            f"`KAMBA_ENV={AMBIENTE_PROD}`: o ficheiro dos ambientes sinteticos "
            "declara destinos autorizados, DPA aceite e referencia de mapa sem "
            "nada disso existir, e carrega-lo em producao activava tenants sem "
            "o que os requisitos 4 e 9 de `E3` exigem. O servico nao arranca "
            "(KAM-069, criterio 8)"
        )


class ConfiguracaoSinteticaInvalida(ValueError):
    """O ficheiro nao serve. A mensagem nomeia a linha, nunca o conteudo dela."""


def exigir_ambiente(ambiente: str, env: Mapping[str, str | None]) -> None:
    """A verificacao no arranque do criterio 8.

    Chama-se **no arranque** do servico e nao a cada activacao: um arranque que
    recusa e visivel, e uma recusa na primeira activacao de um tenant real era
    descobrir o problema no pior momento possivel.

    **Um ambiente desconhecido e tratado como `prod`**, pela mesma escolha do
    `arrancar` do `llm/destinos.py`: um `KAMBA_ENV=producao` escrito por engano
    nao pode servir a politica de `dev`, e aqui o engano custava a activacao de
    um tenant com dados reais.
    """
    conhecido = ambiente in (AMBIENTE_PROD, "staging", "dev")
    efectivo = ambiente if conhecido else AMBIENTE_PROD
    if efectivo != AMBIENTE_PROD:
        return
    declarado = (env.get(VARIAVEL_SINTETICOS) or "").strip()
    if declarado:
        raise ConfiguracaoDeProdInvalida()


def avaliar_go_live(
    destinos: Sequence[DestinoActivo],
    dpa_aceite: bool,
    mapa_ref: str | None,
    mapa_esperado: str | None = None,
) -> tuple[Falta, ...]:
    """As faltas do criterio 8. Pura: nao vai a base nem le o ambiente.

    **Zero destinos nao e uma falta de destino**, e essa e a unica subtileza
    desta funcao. O criterio diz «faltar destino autorizado para **algum destino
    activo** do tenant»: um tenant sem destino nenhum registado nao transfere
    nada para fora, e exigir-lhe um destino autorizado era exigir uma
    autorizacao para uma transferencia que nao acontece. O que o impede de
    activar nesse caso sao as outras duas condicoes, que nao dependem de
    destinos.

    Dito ao contrario, para nao se ler como brecha: isto **nao** afirma que o
    tenant nao transfere. Afirma que esta tabela nao conhece transferencia
    nenhuma dele. Quem garante que uma saida sem linha aqui nao acontece e a
    `PortaSobreDestinos`, que nega por ausencia de linha — a mesma ausencia, no
    outro sentido.
    """
    faltas: list[Falta] = []
    for destino in destinos:
        if destino.autorizado:
            continue
        razao = (
            f"esta `{destino.status}`"
            if estado_bloqueia(destino.status)
            else "nao tem `apd_ref`"
        )
        faltas.append(
            Falta(
                "destino",
                f"`{destino.provider}` com finalidade `{destino.purpose}` "
                f"{razao}",
            )
        )
    if not dpa_aceite:
        faltas.append(
            Falta(
                "dpa",
                "o contrato de subcontratacao (DPA) nao esta aceite por esta "
                "PME; o requisito 4 de `E3` di-lo por extenso («tenant sem DPA "
                "nao activa») e o contrato nao esta redigido. Credor: KAM-090",
            )
        )
    referencia = (mapa_ref or "").strip()
    if not referencia:
        faltas.append(
            Falta(
                "mapa",
                "sem referencia do mapa de tratamentos; o requisito 9 de `E3` "
                "exige o documento versionado e o `docs/tecnica/08` §8.6 "
                "pe-lo como pre-requisito (1) dos dados reais",
            )
        )
    elif not FORMA_DO_MAPA.match(referencia):
        faltas.append(
            Falta(
                "mapa",
                "a referencia do mapa de tratamentos nao tem a forma "
                "`<major>.<n>+<12 hex>`: uma referencia que nao identifica "
                "conteudo nao prova que o mapa descreve este sistema",
            )
        )
    elif mapa_esperado is not None and referencia != mapa_esperado.strip():
        faltas.append(
            Falta(
                "mapa",
                "a referencia do mapa de tratamentos nao e a do mapa vivo: "
                "o inventario ou os destinos mudaram desde que ela foi "
                "escrita, e um mapa desactualizado e um mapa que descreve "
                "outro sistema",
            )
        )
    return tuple(faltas)


def destinos_do_tenant(
    ler: Callable[[str], Sequence[Mapping[str, object]]], tenant_id: str
) -> tuple[DestinoActivo, ...]:
    """Os destinos registados do tenant. **Falha fechada**, como a porta.

    Um erro da base levanta `TransferenciaNegada` e nao devolve lista vazia: uma
    lista vazia lia-se como «este tenant nao transfere nada» e era a leitura
    exactamente ao contrario — a base nao respondeu, nao disse que nao havia
    nada. E a mesma assimetria que o `avaliar_go_live` descreve para zero
    destinos, vista do outro lado: ali a lista vazia e um facto, aqui e uma
    pergunta sem resposta.

    O `ler` e um leitor de linhas e nao uma ligacao: quem o tem pronto e o
    `kamba_core.destinos.dbapi.ler_destinos_do_tenant`, com a ligacao presa por
    `functools.partial`. A razao de o seam estar aqui e a do
    `LeitorDeDestinos` — o contexto de RLS do tenant nao se exprime num
    protocolo de SQL generico.
    """
    try:
        linhas = list(ler(tenant_id))
    except Exception as erro:  # noqa: BLE001 — falha fechada, e por desenho
        raise TransferenciaNegada(
            f"nao se conseguiu ler os destinos do tenant "
            f"({type(erro).__name__}): uma lista vazia lia-se como «nao "
            "transfere nada», e a base nao disse isso (falha fechada, "
            "ADR-008, KAM-069)"
        ) from erro
    destinos = []
    for linha in linhas:
        provider = linha.get("provider")
        purpose = linha.get("purpose")
        status = linha.get("status")
        tem_apd_ref = linha.get("tem_apd_ref")
        if (
            not isinstance(provider, str)
            or not isinstance(purpose, str)
            or not isinstance(status, str)
            or not isinstance(tem_apd_ref, bool)
        ):
            raise TransferenciaNegada(
                "linha ilegivel de `platform.tenant_destinations` ao avaliar o "
                "go-live: uma resposta que nao se le nao autoriza nada "
                "(ADR-008, KAM-069)"
            )
        destinos.append(DestinoActivo(provider, purpose, status, tem_apd_ref))
    return tuple(destinos)


def exigir_go_live(
    ambiente: str,
    tenant_id: str,
    destinos: Sequence[DestinoActivo],
    dpa_aceite: bool,
    mapa_ref: str | None,
    mapa_esperado: str | None = None,
) -> tuple[str, ...]:
    """Levanta `GoLiveNegado` em `prod`; fora de `prod` devolve os avisos.

    **A mesma forma do `fornecedorDeEmail` do KAM-115 e do `agregadorDeSms` do
    KAM-116**, e pela mesma razao: um ambiente de desenvolvimento tem de poder
    activar um tenant sintetico sem papelada, e um ambiente de producao nao.

    Um ambiente desconhecido e tratado como `prod` (ver `exigir_ambiente`).
    """
    faltas = avaliar_go_live(destinos, dpa_aceite, mapa_ref, mapa_esperado)
    if not faltas:
        return ()
    conhecido = ambiente in (AMBIENTE_PROD, "staging", "dev")
    if not conhecido or ambiente == AMBIENTE_PROD:
        raise GoLiveNegado(tenant_id, faltas)
    return tuple(
        f"go-live do tenant {tenant_id} com {falta}; fora de "
        f"`{AMBIENTE_PROD}` e aviso, em `{AMBIENTE_PROD}` o tenant nao activa "
        "(ADR-008, KAM-069)"
        for falta in faltas
    )


@dataclass(frozen=True)
class ConfiguracaoSintetica:
    """O que o ficheiro dos ambientes sinteticos declara.

    Tres coisas, e sao as tres condicoes do criterio 8. Formato de linhas
    `chave = valor`, **nao YAML**: o `kamba_core` nao tem leitor de YAML e nao e
    para aqui que ele devia nascer — o `tools/kamba_yaml.py` existe para as
    ferramentas que correm antes de qualquer instalacao, e uma biblioteca de
    runtime que o importasse ficava a depender de `tools/`.

        # comentario
        mapa_ref = 1.0+0123456789ab
        dpa = aceite
        destino = openai:conversa
        destino = groq:transcricao
    """

    destinos: tuple[DestinoActivo, ...]
    dpa_aceite: bool
    mapa_ref: str | None

    @classmethod
    def ler(
        cls, env: Mapping[str, str | None], raiz: Path | None = None
    ) -> "ConfiguracaoSintetica | None":
        """A configuracao, ou `None` se a variavel nao esta definida.

        Nao verifica o ambiente: quem o faz e o `exigir_ambiente`, no arranque.
        Separar os dois e deliberado — uma funcao que lesse o ficheiro **e**
        decidisse se o podia ler tinha a barreira dentro do caminho que a
        barreira protege.
        """
        declarado = (env.get(VARIAVEL_SINTETICOS) or "").strip()
        if not declarado:
            return None
        caminho = Path(declarado)
        if raiz is not None and not caminho.is_absolute():
            caminho = raiz / caminho
        try:
            texto = caminho.read_text(encoding="utf-8")
        except OSError as erro:
            raise ConfiguracaoSinteticaInvalida(
                f"`{VARIAVEL_SINTETICOS}` aponta para um ficheiro que nao se "
                f"consegue ler ({type(erro).__name__})"
            ) from erro
        return cls.de_texto(texto)

    @classmethod
    def de_texto(cls, texto: str) -> "ConfiguracaoSintetica":
        destinos: list[DestinoActivo] = []
        dpa_aceite = False
        mapa_ref: str | None = None
        for numero, bruta in enumerate(texto.splitlines(), start=1):
            linha = bruta.split("#", 1)[0].strip()
            if not linha:
                continue
            if "=" not in linha:
                raise ConfiguracaoSinteticaInvalida(
                    f"linha {numero}: sem `=`; o formato e `chave = valor`"
                )
            chave, _, valor = linha.partition("=")
            chave = chave.strip()
            valor = valor.strip()
            if chave == "destino":
                if valor.count(":") != 1:
                    raise ConfiguracaoSinteticaInvalida(
                        f"linha {numero}: um `destino` e "
                        "`<fornecedor>:<finalidade>`"
                    )
                provider, _, purpose = valor.partition(":")
                # **Nascem `autorizado` com `apd_ref`, e e isso que o ficheiro
                # e:** a declaracao de que, neste ambiente, aquele par passa.
                # Nenhuma destas linhas afirma nada sobre a APD — e por isso
                # que `prod` recusa arrancar com o ficheiro declarado.
                destinos.append(
                    DestinoActivo(provider.strip(), purpose.strip(), "autorizado", True)
                )
            elif chave == "dpa":
                dpa_aceite = valor == "aceite"
            elif chave == "mapa_ref":
                mapa_ref = valor
            else:
                raise ConfiguracaoSinteticaInvalida(
                    f"linha {numero}: chave `{chave}` desconhecida; as tres sao "
                    "`destino`, `dpa` e `mapa_ref`"
                )
        return cls(tuple(destinos), dpa_aceite, mapa_ref)
