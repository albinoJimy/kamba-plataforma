"""O oraculo: o canario de B nao aparece em nada que A consiga ver.

`docs/tecnica/08` §3.7 define-o em uma linha — «o canario de B nao aparece em
respostas, erros, logs nem traces; qualquer fuga falha o build» — e o criterio 9
do KAM-066 acrescenta o que falta: «o oraculo varre **tambem** logs e traces
OTel de cada caso». Logo cinco origens, e um caso que varra so o corpo nao
cumpriu o criterio.

```text
corpo        o que a rota, a tool ou a consulta devolveu
cabecalhos   incluindo os de erro e os de diagnostico
erro         a excepcao, a mensagem e o SQLSTATE
logs         as linhas que o caso produziu enquanto corria
spans        os atributos dos spans OTel do caso
```

## O que procura, e o que **nao** chega procurar

Procura o canario — a cadeia unica que o *seed* pos numa linha de B — **e o
`tenant_id` de B**. Os dois, porque falham por lados diferentes: um `SELECT`
que vaze a linha traz o canario, e uma mensagem de erro que diga «o tenant
<uuid> nao tem este recurso» nao traz canario nenhum e entrega a existencia de B
de graca. Procurar so o canario deixava passar o segundo, que e o oraculo de
existencia que o criterio 3 nomeia ao pedir «403/404 **uniformes**».

## A sonda positiva, e porque e que esta aqui e nao nos testes

Quatro afirmacoes de «zero canarios» passam todas contra uma tabela vazia, um
oraculo que procure a cadeia errada ou um `varrer` que devolva sempre `[]`. A
casa tem padrao para isto — o `RLS-CONTROLO` fora da contagem, as metades
positivas de `test_x03_x04_isolamento.py` — e aqui ele e o `confirmar_que_morde`:
**cada caso chama-o**, e ele falha se o oraculo nao encontrar um canario que
esta mesmo la. Um caso que se esqueca de o chamar e apanhado pelo registo
(`baterias/` declara `sonda=True` por omissao e o corredor exige a prova).

## Normaliza antes de procurar, e isso nao e cosmetico

Um canario pode sair em `bytes` (uma coluna `bytea`), dentro de um `dict`
aninhado, num `repr` de excepcao ou num atributo de span. Procurar numa cadeia
que o chamador construiu a mao punha a correccao do oraculo a depender de quem
o chama. Este modulo achata o que receber — `bytes` por `latin-1` (que nunca
falha e preserva os octetos), tudo o resto por `repr` recursivo — e procura no
resultado.

**O que isto nao cobre:** um canario que saia cifrado, comprimido ou codificado
(base64, `bytea` em hexadecimal). Fica dito em vez de ficar por dizer: o *seed*
escolhe formas que atravessam em claro (`sementes.Receita.guardado`), e uma
coluna que so guarde o canario transformado precisa de um caso que o procure na
forma transformada.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping

#: A forma do canario deste conjunto. **Nao e a do bloco**, e a razao e medida:
#: os Detalhes Tecnicos escrevem `CANARY-{tenant}-{tabela}-{uuid}`, e o canario
#: tem de caber em `platform.entitlements.modulo`, que e um identificador em
#: minusculas e `snake_case` (dicionario §3.2). A forma abaixo e a que o KAM-004
#: fixou e a que 45 receitas de `db/tests_isolamento/sementes.py` ja produzem;
#: mudar a forma era reescrever as 45 para ganhar maiusculas.
FORMA_DO_CANARIO = re.compile(r"^canario_[a-z0-9]+_[0-9a-f]{32}$")

#: As cinco origens do criterio 9. Um caso que varra menos do que as que tem
#: fica com um achado do corredor, nao com um verde.
ORIGENS = ("corpo", "cabecalhos", "erro", "logs", "spans")


class OraculoCego(RuntimeError):
    """A sonda positiva falhou: o oraculo nao encontrou um canario que esta la.

    E a unica excepcao deste modulo, e e a que importa. Um oraculo que nao morde
    torna verdes todas as afirmacoes de «zero canarios» da suite — e uma suite
    de isolamento verde com a RLS desligada e pior do que nenhuma, porque da
    confianca.
    """


@dataclasses.dataclass(frozen=True)
class Fuga:
    """Um canario encontrado onde nao podia estar."""

    origem: str
    #: O rotulo do que vazou (`platform.price_quotes`, `tenant_id`).
    rotulo: str
    #: Os 24 caracteres em volta. **Nunca o canario inteiro**: o relatorio do
    #: *gate* e publico, e um canario completo num log de CI e um valor com
    #: forma de segredo a atravessar o varrimento do gate 9.
    contexto: str

    def __str__(self) -> str:
        return f"{self.origem}: vazou {self.rotulo} (…{self.contexto}…)"


def achatar(valor: object) -> str:
    """Tudo o que possa conter um canario, numa cadeia onde se possa procurar."""
    if isinstance(valor, str):
        return valor
    if isinstance(valor, bytes | bytearray | memoryview):
        # `latin-1` nunca levanta e preserva os octetos um a um: um canario
        # ASCII numa coluna `bytea` atravessa intacto.
        return bytes(valor).decode("latin-1")
    if isinstance(valor, Mapping):
        return " ".join(
            f"{achatar(chave)}={achatar(item)}" for chave, item in valor.items()
        )
    if isinstance(valor, BaseException):
        # A classe **e** a mensagem: um `NotFoundError` e um `ForbiddenError`
        # distinguem-se pela classe, e e isso que o criterio 3 chama a falta de
        # uniformidade.
        return f"{type(valor).__name__}: {valor}"
    if isinstance(valor, Iterable):
        return " ".join(achatar(item) for item in valor)
    return repr(valor)


class Oraculo:
    """Procura os canarios de um tenant em tudo o que o outro consiga ver.

        oraculo = Oraculo({"platform.tenants": "canario_b_ab…", "tenant_id": uuid})
        oraculo.confirmar_que_morde()
        fugas = oraculo.varrer("corpo", resposta.json())
    """

    def __init__(self, proibidos: Mapping[str, object]) -> None:
        self._proibidos = {
            rotulo: achatar(valor)
            for rotulo, valor in proibidos.items()
            if achatar(valor) != ""
        }
        if not self._proibidos:
            raise OraculoCego(
                "um oraculo sem nada proibido nao mede nada: toda a afirmacao "
                "de «zero canarios» passava. Passe os canarios de B e o "
                "`tenant_id` dele."
            )
        curtos = {
            rotulo: len(texto)
            for rotulo, texto in self._proibidos.items()
            if len(texto) < 8
        }
        if curtos:
            raise OraculoCego(
                f"canarios demasiado curtos para serem unicos: {curtos}. Um "
                "canario de poucos caracteres aparece por acidente em qualquer "
                "corpo, e o oraculo passa a dar falsos positivos — que se "
                "aprende a ignorar."
            )

    @property
    def proibidos(self) -> dict[str, str]:
        return dict(self._proibidos)

    def varrer(self, origem: str, valor: object) -> list[Fuga]:
        """As fugas em `valor`. Lista vazia quer dizer que nada de B saiu."""
        if origem not in ORIGENS:
            raise OraculoCego(
                f"origem {origem!r} fora de {ORIGENS}: o criterio 9 nomeia as "
                "cinco, e uma origem inventada nao entra na contagem do caso."
            )
        texto = achatar(valor)
        fugas: list[Fuga] = []
        for rotulo, proibido in self._proibidos.items():
            posicao = texto.find(proibido)
            if posicao < 0:
                continue
            inicio = max(0, posicao - 12)
            fugas.append(
                Fuga(
                    origem=origem,
                    rotulo=rotulo,
                    contexto=texto[inicio : posicao + 12].replace("\n", " "),
                )
            )
        return fugas

    def varrer_tudo(self, por_origem: Mapping[str, object]) -> list[Fuga]:
        """Varre varias origens de uma vez. As que faltarem **nao** sao varridas.

        Nao se exige aqui que as cinco venham: um caso de tool nao tem
        cabecalhos. Quem exige a cobertura das origens e o corredor, que compara
        as origens varridas com as que o caso declarou ter.
        """
        fugas: list[Fuga] = []
        for origem, valor in por_origem.items():
            fugas.extend(self.varrer(origem, valor))
        return fugas

    def confirmar_que_morde(self) -> None:
        """A sonda positiva. Levanta `OraculoCego` se o oraculo nao encontrar.

        Constroi, para cada canario, um corpo que o contem — nas tres formas em
        que ele pode sair (cadeia, octetos, dentro de um mapa) — e exige que o
        `varrer` o encontre nas tres. Sem isto, as afirmacoes de «zero fugas»
        de todos os casos passavam com um `varrer` que devolvesse sempre `[]`.
        """
        for rotulo, proibido in self._proibidos.items():
            formas: dict[str, object] = {
                "cadeia": f"ruido antes {proibido} ruido depois",
                "octetos": proibido.encode("latin-1"),
                "mapa": {"linha": {"coluna": proibido}},
                "lista": ["a", proibido, "b"],
            }
            for forma, valor in formas.items():
                if not self.varrer("corpo", valor):
                    raise OraculoCego(
                        f"a sonda positiva falhou: o oraculo nao encontrou "
                        f"{rotulo} na forma {forma!r}. Enquanto isto falhar, "
                        "toda a afirmacao de «zero canarios» desta suite e "
                        "verde sem medir nada."
                    )
