"""O inventario de subprocessadores: leitura, validacao e versao (KAM-069).

Le o `gov/subprocessadores.yaml` com o `kamba_yaml` — o subconjunto da
biblioteca padrao, pela razao que esse modulo escreve — e **recusa em voz alta**
o que nao sirva. Um inventario que se leia pela metade e pior do que nenhum: a
lista publica que dele sai e um compromisso com os titulares dos dados.

## A validacao e sobre o que o criterio 6 pede, e nada mais

«Por destino ficam arquivados contrato, retencao zero, nao-treino e `apd_ref`
(*checklist* do requisito 8); um destino `autorizado` sem *checklist* completo e
rejeitado.» E isso que o `validar` impoe, e e a **mesma** regra que o
`tenant_destinations_autorizado_com_checklist_ck` da revisao `0036` impoe na
base — de proposito: o inventario e o documento e a tabela e a configuracao, e
uma a aceitar o que a outra recusa punha o documento a descrever uma
configuracao impossivel.

**O que as duas superficies tem em comum e a *checklist*, e nao mais do que
isso**, e a revisao adversarial mostrou que a frase anterior afirmava a
equivalencia inteira. Nao e verdade, e as duas diferencas dizem-se:

* a base exige tambem a **janela** de uma linha `autorizado`
  (`autorizado_em IS NOT NULL AND revogado_em IS NULL`), e o inventario nao tem
  campo de janela — ele descreve o subprocessador, nao a configuracao por
  tenant;
* o `pais_hipotese` e **texto livre** aqui («EUA ou UE», «por decidir») e o
  `country` da tabela e `^[A-Z]{2}$`. E deliberado: o §8.3.2 chama-lhes
  hipoteses e uma hipotese nao cabe num codigo ISO.

O que se afirma, e que se verifica, e mais estreito: **uma linha `autorizado`
sem a *checklist* completa e recusada nas duas**.

**O que a validacao nao faz: nao julga a escolha.** Nenhuma regra aqui diz que
pais e aceitavel, nem que fornecedor e preferivel. O codigo nunca infere
adequacao (ADR-008) e escolher um subprocessador num ficheiro de codigo e
exactamente o que esse ADR existe para impedir.

## A versao deriva do conteudo, e e o criterio 9

«O mapa de tratamentos e um documento versionado gerado do inventario e de
`tenant_destinations`; **alterar uma linha altera a versao**.» Um numero escrito
a mao nao tem essa propriedade — esquece-se —, pelo que a versao e
`<versao declarada>+<12 primeiros digitos do sha256 das linhas normalizadas>`.

**Normalizadas** quer dizer: os campos que decidem, por ordem, sem as `nota`. E
a mesma ideia do `ci/llm-aliases.lock` do KAM-030, que exclui os comentarios, e
pela mesma razao — o que se *hasheia* e o conteudo que decide, nao o texto que o
descreve. Reescrever uma `nota` nao e alterar um tratamento; mudar um pais e.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from kamba_yaml import YamlSubsetError, load_file

#: Onde vive o inventario, relativo a raiz do repositorio.
CAMINHO = "gov/subprocessadores.yaml"

#: As **onze** linhas do `docs/tecnica/08` §8.3.2.
#:
#: **Numero fixo no codigo e nao lido do ficheiro**, e isso e a diferenca entre
#: um verificador e um espelho: o criterio 5 pede «as 11 linhas de §8.3.2», e um
#: minimo lido do proprio ficheiro passava com uma linha apagada. Acrescentar um
#: subprocessador e uma alteracao aqui **e** uma emenda ao §8.3.2, que e o que
#: mantem as duas superficies a dizer o mesmo.
LINHAS_ESPERADAS = 11

#: As finalidades de `platform.tenant_destinations.purpose` (revisao `0036`, e a
#: `imagem` da revisao `foto_de_produtos`, KAM-120).
#:
#: **Catorze, e a lista nao se importa de `kamba_core`**: as ferramentas correm
#: antes de qualquer instalacao (ver `kamba_yaml`), e `tools/` nao depende de
#: `libs/`. A paridade entre as duas copias e um teste
#: (`test_as_finalidades_sao_as_do_nucleo`), que e a forma desta casa para
#: duas listas que tem de dizer o mesmo sem uma depender da outra.
FINALIDADES = (
    "alojamento",
    "canal",
    "conversa",
    "copias_de_seguranca",
    "embeddings",
    "entrega_de_conteudo",
    "facturacao",
    "imagem",
    "observabilidade",
    "otp_e_avisos_de_servico",
    "pagamentos",
    "segredos",
    "transcricao",
    "visao",
)

#: Os **quatro** estados, da mesma revisao.
ESTADOS = ("pendente", "autorizado", "revogado", "negado")
ESTADO_AUTORIZADO = "autorizado"

#: A forma do `nome`: e o `provider` da `0036`, e tem o `CHECK` dela.
FORMA_DO_NOME = re.compile(r"^[a-z][a-z0-9_-]{1,62}$")

#: A forma do `apd_ref`, tambem da `0036`.
FORMA_DO_APD_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$")

#: A forma do `credor`: um ticket `KAM-NNN` ou uma decisao aberta `DN`.
#:
#: **Exige-se um dos dois e nao texto livre**, pela regra desta casa: «uma caixa
#: que fica aberta leva o credor escrito». `a tratar` nao e um credor.
FORMA_DO_CREDOR = re.compile(r"^(KAM-[0-9]{3}|D[0-9]{1,2})$")

#: A forma da versao declarada: `<major>.<minor>`, em SemVer curto.
FORMA_DA_VERSAO = re.compile(r"^[0-9]+\.[0-9]+$")

#: Os campos de cada linha, todos obrigatorios.
CAMPOS = (
    "nome",
    "designacao",
    "funcao",
    "dados_pessoais",
    "pais_hipotese",
    "pais_verificado",
    "estado",
    "finalidades",
    "contrato_ref",
    "retencao_zero",
    "sem_treino",
    "apd_ref",
    "credor",
    "nota",
)

#: Os campos que entram no *hash* da versao, por esta ordem. **Sem a `nota`** —
#: ver a nota do modulo.
CAMPOS_QUE_DECIDEM = (
    "nome",
    "designacao",
    "funcao",
    "dados_pessoais",
    "pais_hipotese",
    "pais_verificado",
    "estado",
    "finalidades",
    "contrato_ref",
    "retencao_zero",
    "sem_treino",
    "apd_ref",
    "credor",
)


class InventarioInvalido(ValueError):
    """O inventario nao serve. A mensagem nomeia a linha e o campo."""


@dataclass(frozen=True)
class Subprocessador:
    nome: str
    designacao: str
    funcao: str
    dados_pessoais: str
    pais_hipotese: str
    pais_verificado: bool
    estado: str
    finalidades: tuple[str, ...]
    contrato_ref: str | None
    retencao_zero: bool
    sem_treino: bool
    apd_ref: str | None
    credor: str
    nota: str

    @property
    def checklist_completa(self) -> bool:
        """As quatro coisas do requisito 8 de `E3`, todas."""
        return (
            self.contrato_ref is not None
            and self.retencao_zero
            and self.sem_treino
            and self.apd_ref is not None
        )

    @property
    def autorizado(self) -> bool:
        return self.estado == ESTADO_AUTORIZADO


@dataclass(frozen=True)
class Inventario:
    versao: str
    subprocessadores: tuple[Subprocessador, ...]

    @property
    def nao_autorizados(self) -> tuple[Subprocessador, ...]:
        """Os que **nao** estao `autorizado` — e nao «os pendentes».

        **Chamava-se `pendentes` e o nome mentia**, como a revisao adversarial
        mediu: o predicado e `not autorizado`, pelo que um destino `revogado` ou
        `negado` entrava na conta e a saida do *gate* reportava-o como pendente.
        Hoje as onze linhas estao mesmo `pendente` e os dois nomes davam o mesmo
        numero; o dia em que uma ficasse `negado`, o numero continuava certo e a
        palavra errada.
        """
        return tuple(s for s in self.subprocessadores if not s.autorizado)

    @property
    def pendentes(self) -> tuple[Subprocessador, ...]:
        """Os que estao `pendente`, pelo estado e nao por exclusao."""
        return tuple(s for s in self.subprocessadores if s.estado == "pendente")

    def versao_do_mapa(self, destinos: tuple[dict, ...] = ()) -> str:
        """`<versao>+<12 hex>`, sobre o inventario **e** os destinos.

        Os destinos entram porque o criterio 9 diz «gerado do inventario **e de
        `tenant_destinations`**»: uma versao que ignorasse a configuracao ficava
        igual depois de alguem autorizar um destino, e era precisamente essa
        mudanca que o mapa tem de registar.

        O `json.dumps` com `sort_keys` e `separators` fixos: a serializacao tem
        de ser a mesma em maquinas diferentes, ou o *hash* muda sem o conteudo
        mudar — e um *hash* instavel transforma o criterio 9 em ruido.
        """
        corpo = {
            "inventario": [
                {campo: getattr(s, campo) for campo in CAMPOS_QUE_DECIDEM}
                for s in self.subprocessadores
            ],
            "destinos": [dict(sorted(d.items())) for d in destinos],
        }
        bruto = json.dumps(
            corpo, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        digest = hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:12]
        return f"{self.versao}+{digest}"


def _exigir(condicao: bool, mensagem: str) -> None:
    if not condicao:
        raise InventarioInvalido(mensagem)


def _ler_linha(indice: int, bruta: object) -> Subprocessador:
    onde = f"subprocessadores[{indice}]"
    _exigir(isinstance(bruta, dict), f"{onde}: cada entrada e um mapa")
    assert isinstance(bruta, dict)  # para o verificador de tipos
    faltam = [campo for campo in CAMPOS if campo not in bruta]
    _exigir(not faltam, f"{onde}: sem {', '.join(faltam)}")
    sobram = sorted(set(bruta) - set(CAMPOS))
    _exigir(not sobram, f"{onde}: campo(s) desconhecido(s): {', '.join(sobram)}")

    nome = bruta["nome"]
    _exigir(
        isinstance(nome, str) and bool(FORMA_DO_NOME.match(nome)),
        f"{onde}: `nome` tem de casar {FORMA_DO_NOME.pattern} (e o `provider` "
        "de `platform.tenant_destinations`)",
    )
    for campo in ("designacao", "funcao", "dados_pessoais", "pais_hipotese", "nota"):
        valor = bruta[campo]
        _exigir(
            isinstance(valor, str) and valor.strip() != "",
            f"{onde}: `{campo}` tem de ser texto nao vazio",
        )
    for campo in ("pais_verificado", "retencao_zero", "sem_treino"):
        _exigir(
            isinstance(bruta[campo], bool),
            f"{onde}: `{campo}` tem de ser `true` ou `false`",
        )
    estado = bruta["estado"]
    _exigir(
        estado in ESTADOS,
        f"{onde}: `estado` tem de ser um de {', '.join(ESTADOS)}",
    )
    finalidades = bruta["finalidades"]
    _exigir(
        isinstance(finalidades, list) and finalidades != [],
        f"{onde}: `finalidades` tem de ser uma lista nao vazia",
    )
    assert isinstance(finalidades, list)
    fora = [f for f in finalidades if f not in FINALIDADES]
    _exigir(
        not fora,
        f"{onde}: finalidade(s) fora do dominio de "
        f"`tenant_destinations.purpose`: {', '.join(map(str, fora))}",
    )
    _exigir(
        len(set(finalidades)) == len(finalidades),
        f"{onde}: `finalidades` tem repeticoes",
    )
    for campo in ("contrato_ref", "apd_ref"):
        valor = bruta[campo]
        _exigir(
            valor is None or (isinstance(valor, str) and valor.strip() != ""),
            f"{onde}: `{campo}` e texto nao vazio ou `null`",
        )
    apd_ref = bruta["apd_ref"]
    _exigir(
        apd_ref is None or bool(FORMA_DO_APD_REF.match(str(apd_ref))),
        f"{onde}: `apd_ref` nao tem a forma de uma referencia",
    )
    credor = bruta["credor"]
    _exigir(
        isinstance(credor, str) and bool(FORMA_DO_CREDOR.match(credor)),
        f"{onde}: `credor` tem de ser `KAM-NNN` ou `DN` — «a tratar» nao e um "
        "credor",
    )
    return Subprocessador(
        nome=str(nome),
        designacao=str(bruta["designacao"]),
        funcao=str(bruta["funcao"]),
        dados_pessoais=str(bruta["dados_pessoais"]),
        pais_hipotese=str(bruta["pais_hipotese"]),
        pais_verificado=bool(bruta["pais_verificado"]),
        estado=str(estado),
        finalidades=tuple(str(f) for f in finalidades),
        contrato_ref=None if bruta["contrato_ref"] is None else str(bruta["contrato_ref"]),
        retencao_zero=bool(bruta["retencao_zero"]),
        sem_treino=bool(bruta["sem_treino"]),
        apd_ref=None if apd_ref is None else str(apd_ref),
        credor=str(credor),
        nota=str(bruta["nota"]),
    )


def validar(inventario: Inventario) -> None:
    """As regras que olham para o inventario inteiro.

    Sao tres, e cada uma fecha uma falha diferente:

    1. **As onze linhas do §8.3.2.** Numero fixo — ver a nota de
       `LINHAS_ESPERADAS`.
    2. **Nomes unicos.** Dois `openai` davam duas verdades sobre o mesmo
       destino, e a lista publica nomeava-o duas vezes.
    3. **`autorizado` exige a *checklist* completa**, que e o criterio 6 e a
       mesma regra do `CHECK` da revisao `0036`.
    """
    quantas = len(inventario.subprocessadores)
    _exigir(
        quantas == LINHAS_ESPERADAS,
        f"o inventario tem {quantas} linhas e o `docs/tecnica/08` §8.3.2 tem "
        f"{LINHAS_ESPERADAS}: acrescentar ou retirar um subprocessador e uma "
        "emenda a esse documento e a este ficheiro, nunca a um so",
    )
    nomes = [s.nome for s in inventario.subprocessadores]
    repetidos = sorted({n for n in nomes if nomes.count(n) > 1})
    _exigir(
        not repetidos,
        f"nome(s) repetido(s) no inventario: {', '.join(repetidos)}",
    )
    for s in inventario.subprocessadores:
        if s.autorizado and not s.checklist_completa:
            faltas = []
            if s.contrato_ref is None:
                faltas.append("`contrato_ref`")
            if not s.retencao_zero:
                faltas.append("`retencao_zero`")
            if not s.sem_treino:
                faltas.append("`sem_treino`")
            if s.apd_ref is None:
                faltas.append("`apd_ref`")
            raise InventarioInvalido(
                f"`{s.nome}` esta `{ESTADO_AUTORIZADO}` e a *checklist* do "
                f"requisito 8 de `E3` esta incompleta (falta {', '.join(faltas)}): "
                "um destino autorizado sem evidencia arquivada e uma "
                "autorizacao que ninguem pode mostrar (KAM-069, criterio 6)"
            )


def ler(raiz: Path) -> Inventario:
    """O inventario, lido e validado. Levanta `InventarioInvalido` se nao serve."""
    caminho = raiz / CAMINHO
    try:
        documento = load_file(caminho)
    except YamlSubsetError as erro:
        raise InventarioInvalido(str(erro)) from erro
    _exigir(documento.get("version") == 1, f"{CAMINHO}: `version` tem de ser 1")
    versao = documento.get("versao")
    _exigir(
        isinstance(versao, str) and bool(FORMA_DA_VERSAO.match(versao)),
        f"{CAMINHO}: `versao` tem de ser `<major>.<minor>` entre aspas",
    )
    linhas = documento.get("subprocessadores")
    _exigir(
        isinstance(linhas, list) and linhas != [],
        f"{CAMINHO}: `subprocessadores` tem de ser uma lista nao vazia",
    )
    assert isinstance(linhas, list)
    inventario = Inventario(
        versao=str(versao),
        subprocessadores=tuple(
            _ler_linha(indice, bruta) for indice, bruta in enumerate(linhas)
        ),
    )
    validar(inventario)
    return inventario
