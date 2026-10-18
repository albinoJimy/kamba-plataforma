"""Validacao de `ci/waivers.yaml` — o unico mecanismo de excepcao do pipeline.

A regra transversal do §4 do Engineering Standards diz: «nenhum gate pode ser
marcado *skip* sem ADR ou aprovacao registada». Dois tickets a jusante repetem a
exigencia com palavras diferentes — o KAM-067 diz «excepcao registada em ADR» e o
KAM-078 diz «exige referencia a ADR/aprovacao (*lint* do pipeline)» — e ambos
consomem este esquema, em vez de inventarem o seu.

O que este modulo recusa, e porque:

| Recusa | Razao |
|---|---|
| sem `adr_ou_aprovacao` | uma excepcao sem fundamento e uma decisao sem autor |
| sem `expira_em` | uma excepcao sem prazo fica para sempre |
| `expira_em` > 30 dias | o limite e *proposta* do ticket, e e ele que a torna temporaria |
| **expirado** | **falha o pipeline** — nao avisa, nao ignora |
| sem `alvo` | uma excepcao que nao diz a quem se aplica aplica-se a tudo |
| sem `razao` | a razao e o que sobrevive a saida do autor |

A recusa de um waiver expirado e a parte que importa. A alternativa — avisar e
seguir — produz excepcoes que ninguem revisita, porque nada obriga a isso.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import re
import sys
from pathlib import Path

from kamba_yaml import YamlSubsetError, exigir_chaves, load_file

#: Limite de validade de um waiver, em dias. *Proposta* do ticket KAM-002.
#:
#: O KAM-135 **nao** mexe no numero; mexe em **a partir de quando se conta**,
#: que e o defeito: contado de hoje, um waiver renova-se para sempre com um
#: diff de um caractere.
PRAZO_MAXIMO_DIAS = 30

#: Gates que aceitam waiver, e a razao de cada ausencia (KAM-135).
#:
#: O conjunto deixou de poder divergir do canon em silencio: a tabela do
#: `specs/01` §4 tem dezoito gates, e cada um esta aqui ou em
#: `GATES_SEM_WAIVER_COM_RAZAO`. Um gate novo no canon e um gate que nenhum dos
#: dois nomeia — e ha um teste que o diz.
GATES_COM_WAIVER = {
    "3", "4", "5", "6", "7", "8", "9", "11",
    # Acrescentados pelo KAM-135. O §5 do `docs/ci.md` diz que o KAM-067 e o
    # KAM-078 consomem **este** esquema em vez de inventarem o seu, e os gates
    # deles sao estes dois (tabela de fronteira do §3). Ate aqui o validador
    # **recusava-os** — o KAM-067 ia encontrar o mecanismo fechado, e a
    # tentacao de inventar o seu e precisamente o que o §5 existe para evitar.
    "14",  # imagem: vulnerabilidades, digest, cosign (KAM-067)
    "18",  # release sem SBOM (KAM-078)
}

#: Os gates que **nao** aceitam waiver, com a razao escrita ao lado. Estar nesta
#: lista e uma decisao, nao um esquecimento — e a diferenca entre as duas coisas
#: era invisivel antes do KAM-135.
GATES_SEM_WAIVER_COM_RAZAO = {
    "1": "um build que nao compila corrige-se, nao se dispensa",
    "2": "um tipo que nao verifica corrige-se, nao se dispensa",
    "10": "SAST nao tem ticket nem implementacao (docs/ci.md §7, lacuna 3); "
          "abrir-lhe a porta antes de ele existir e prometer uma excepcao a "
          "um gate que ninguem pode correr",
    "12": "politica de categorias (KAM-088): e lei e Termos da Meta, nao "
          "qualidade de codigo. Uma categoria proibida nao se dispensa por "
          "trinta dias",
    "13": "eval golden PT-AO: o limiar e a baseline, e dispensa-la e mover a "
          "baseline sem o dizer. Faz-se mexendo na baseline, com revisao",
    "15": "smoke ponta a ponta em staging: se nao passa, nao se promove. E a "
          "ultima verificacao antes de producao",
    "16": "aprovacao humana. Um waiver a uma aprovacao humana e a aprovacao a "
          "dispensar-se a si propria",
    "17": "deploy em producao: nao e uma verificacao, e um acto",
}

#: A tabela de gates do canon, de onde os dois conjuntos acima tem de dar
#: conta. Le-se do `specs/01` §4 em vez de se escrever aqui: uma lista a mao
#: envelhece em silencio, e o criterio do KAM-135 pede exactamente o contrario
#: — «um gate que o canon nomeia e que o conjunto nao inclui e um defeito
#: visivel». A leitura e a mesma classe de verificacao que o `lint_contagens`
#: faz as contagens em prosa: derivar da fonte, nunca copiar.
CANON_DOS_GATES = Path("specs") / "01_Engineering_Standards_e_Handoff.md"

_LINHA_DE_GATE = re.compile(r"^\|\s*(\d{1,2})\s*\|\s*\*\*", re.M)


#: A raiz deste repositorio, derivada da posicao deste ficheiro. O canon lê-se
#: daqui e **nao** do `--root`: o `--root` diz qual `ci/waivers.yaml` validar —
#: nos testes, uma pasta sintetica —, enquanto a cobertura dos gates e uma
#: propriedade das constantes deste modulo contra o canon **deste**
#: repositorio. Sao duas perguntas diferentes, e misturá-las punha qualquer
#: *fixture* a precisar de uma copia do `specs/01`.
RAIZ_DO_REPOSITORIO = Path(__file__).resolve().parent.parent


def gates_do_canon(raiz: Path | None = None) -> set[str]:
    """Os numeros de gate que a tabela do `specs/01` §4 declara."""
    caminho = (raiz or RAIZ_DO_REPOSITORIO) / CANON_DOS_GATES
    if not caminho.is_file():
        raise WaiverInvalido(f"ficheiro em falta: {caminho}")
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as excepcao:
        raise ConfiguracaoIlegivel(f"{caminho}: {excepcao}") from excepcao
    numeros = set(_LINHA_DE_GATE.findall(texto))
    if not numeros:
        # Fail-closed: se a tabela mudar de forma, isto nao pode dar «nenhum
        # gate» e passar — daria verde por nao ter conseguido ler nada.
        raise ConfiguracaoIlegivel(
            f"{caminho}: nao se encontrou a tabela de gates do §4. O formato "
            "mudou, e a verificacao de que o conjunto de waivers acompanha o "
            "canon ficaria vazia sem ninguem reparar."
        )
    return numeros


_ADR = re.compile(r"^ADR-[0-9]{3}$")
_ADR_LOCAL = re.compile(r"^ADR-L[0-9]{3}$")
_APROVACAO = re.compile(r"^aprovacao:[^@\s]+@(?P<data>\d{4}-\d{2}-\d{2})$")

_CAMPOS = (
    "gate", "alvo", "adr_ou_aprovacao", "autor", "razao",
    # `criado_em` entra no KAM-135. Sem ele o prazo contava-se de hoje, e
    # prolongar uma excepcao era empurrar o `expira_em` — um diff de um
    # caractere, sem decisao nova e sem dono novo.
    "criado_em", "expira_em",
)

#: As chaves de topo que este leitor conhece (KAM-134).
_CHAVES = {"version", "waivers"}

#: E as de cada waiver. E exactamente `_CAMPOS`, e nao por acaso: um waiver nao
#: tem campos opcionais. A chave `regra`, que o cabecalho do ficheiro
#: documentava e o exemplo escrevia, **nunca esteve aqui** — e era essa a
#: leitura errada mais perigosa das que o KAM-134 fechou: quem escrevesse
#: `regra: licenca` acreditava ter dispensado so a licenca, e tinha dispensado
#: tambem a vulnerabilidade. Hoje escrever `regra` da erro de configuracao.
_CHAVES_DE_WAIVER = set(_CAMPOS)


class WaiverInvalido(RuntimeError):
    """O ficheiro de waivers esta malformado, ou um waiver expirou."""


class ConfiguracaoIlegivel(WaiverInvalido):
    """`ci/waivers.yaml` nao se le: o leitor recusou-o.

    Separa-se de `WaiverInvalido` por causa do codigo de saida (KAM-136): uma
    recusa do leitor e um **erro de configuracao** (2), nao um achado (1).
    Subclasse, e nao irma, para que quem ja apanhava `WaiverInvalido` continue
    a apanhar isto.
    """


def _data(valor, onde: str) -> _datetime.date:
    try:
        return _datetime.date.fromisoformat(str(valor))
    except (TypeError, ValueError) as excepcao:
        raise WaiverInvalido(
            f"{onde}: `expira_em` tem de ser uma data ISO (AAAA-MM-DD), lido {valor!r}"
        ) from excepcao


def verificar_cobertura_dos_gates(raiz: Path | None = None) -> None:
    """Cada gate do canon aceita waiver, ou diz por escrito porque nao.

    **Nao vive dentro do `ler`**, e a razao e de desenho: isto e uma
    propriedade das constantes deste modulo contra o `specs/01` §4, e nao do
    `ci/waivers.yaml`. Posta no `ler`, obrigava qualquer *fixture* de um waiver
    a trazer uma copia do canon — e um teste que precisa de montar meio
    repositorio para verificar uma linha e um teste que ninguem escreve.

    Corre no `main`, pelo que o `make ci-waivers` a verifica em cada PR, e tem
    bateria propria contra a raiz real.
    """
    descobertos = gates_do_canon(raiz)
    sem_decisao = sorted(
        descobertos - set(GATES_COM_WAIVER) - set(GATES_SEM_WAIVER_COM_RAZAO),
        key=int,
    )
    if sem_decisao:
        raise ConfiguracaoIlegivel(
            f"{CANON_DOS_GATES.as_posix()} nomeia o(s) gate(s) "
            f"{', '.join(sem_decisao)}, que nao estao em `GATES_COM_WAIVER` nem "
            "em `GATES_SEM_WAIVER_COM_RAZAO`. Cada gate do canon ou aceita "
            "waiver, ou diz por escrito porque nao — nao ha terceira posicao."
        )
    inventados = sorted(
        (set(GATES_COM_WAIVER) | set(GATES_SEM_WAIVER_COM_RAZAO)) - descobertos,
        key=int,
    )
    if inventados:
        raise ConfiguracaoIlegivel(
            f"o(s) gate(s) {', '.join(inventados)} estao classificados em "
            f"`tools/ci_waivers.py` e nao existem em "
            f"{CANON_DOS_GATES.as_posix()} §4."
        )


def ler(raiz: Path, hoje: _datetime.date | None = None) -> list[dict]:
    """Le e valida `ci/waivers.yaml`. Levanta se algo estiver errado."""
    caminho = raiz / "ci" / "waivers.yaml"
    if not caminho.is_file():
        raise WaiverInvalido(f"ficheiro em falta: {caminho}")
    try:
        dados = load_file(caminho)
    except YamlSubsetError as excepcao:
        raise ConfiguracaoIlegivel(str(excepcao)) from excepcao
    exigir_chaves(dados, _CHAVES, str(caminho), erro=ConfiguracaoIlegivel)
    if dados.get("version") != 1:
        raise WaiverInvalido(f"{caminho}: 'version' tem de ser 1")

    hoje = hoje or _datetime.date.today()

    waivers = dados.get("waivers")
    if waivers is None:
        raise WaiverInvalido(
            f"{caminho}: falta a chave `waivers`. Use `waivers: []` para dizer "
            "«nenhuma excepcao» — a ausencia da chave e ambigua."
        )
    if not isinstance(waivers, list):
        raise WaiverInvalido(f"{caminho}: `waivers` tem de ser uma lista")

    validados: list[dict] = []
    for indice, waiver in enumerate(waivers, start=1):
        onde = f"{caminho}: waiver {indice}"
        if not isinstance(waiver, dict):
            raise WaiverInvalido(f"{onde}: esperava um mapa")
        exigir_chaves(waiver, _CHAVES_DE_WAIVER, onde, erro=ConfiguracaoIlegivel)

        faltam = [c for c in _CAMPOS if not waiver.get(c)]
        if faltam:
            raise WaiverInvalido(f"{onde}: campos obrigatorios em falta: {', '.join(faltam)}")

        gate = str(waiver["gate"])
        if gate not in GATES_COM_WAIVER:
            raise WaiverInvalido(
                f"{onde}: o gate {gate} nao aceita waiver (aceitam: "
                f"{', '.join(sorted(GATES_COM_WAIVER))}). Um build que nao compila "
                "ou um tipo que nao verifica corrige-se, nao se dispensa."
            )

        referencia = str(waiver["adr_ou_aprovacao"])
        aprovacao = _APROVACAO.match(referencia)
        if not (_ADR.match(referencia) or _ADR_LOCAL.match(referencia) or aprovacao):
            raise WaiverInvalido(
                f"{onde}: `adr_ou_aprovacao` tem de ser `ADR-NNN`, `ADR-LNNN` ou "
                f"`aprovacao:<quem>@<AAAA-MM-DD>`; lido {referencia!r}"
            )
        if aprovacao:
            # A presenca do campo era verificada; o **conteudo** nao. Um
            # `@9999-99-99` passava, e com ele a exigencia de «aprovacao
            # registada» do `specs/01` §4 ficava satisfeita sem registar nada
            # (KAM-135).
            texto = aprovacao.group("data")
            try:
                quando = _datetime.date.fromisoformat(texto)
            except ValueError as excepcao:
                raise WaiverInvalido(
                    f"{onde}: `adr_ou_aprovacao` tem a data {texto!r}, que nao e "
                    "uma data. Uma aprovacao com data inventada satisfaz a "
                    "exigencia de «aprovacao registada» sem registar nada."
                ) from excepcao
            if quando > hoje:
                raise WaiverInvalido(
                    f"{onde}: a aprovacao esta datada de {texto} e hoje e "
                    f"{hoje.isoformat()}. Ninguem aprovou isto ainda."
                )

        if len(str(waiver["razao"])) < 40:
            raise WaiverInvalido(
                f"{onde}: a razao tem {len(str(waiver['razao']))} caracteres. "
                "Uma excepcao justificada em meia linha nao sobrevive a saida do "
                "autor — escreva o que a torna aceitavel e quando rever."
            )

        criado = _data(waiver["criado_em"], f"{onde}: `criado_em`")
        expira = _data(waiver["expira_em"], f"{onde}: `expira_em`")
        if criado > hoje:
            raise WaiverInvalido(
                f"{onde}: `criado_em` e {criado.isoformat()} e hoje e "
                f"{hoje.isoformat()}. Um waiver nao se cria no futuro — e a "
                "forma mais simples de esticar o prazo sem parecer que se "
                "esticou."
            )
        if expira < criado:
            raise WaiverInvalido(
                f"{onde}: `expira_em` ({expira.isoformat()}) e anterior a "
                f"`criado_em` ({criado.isoformat()})."
            )
        if expira < hoje:
            raise WaiverInvalido(
                f"{onde}: **expirou** a {expira.isoformat()} (hoje e "
                f"{hoje.isoformat()}). Um waiver expirado falha o pipeline: ou se "
                "corrige o que ele dispensava, ou se renova com razao nova."
            )
        # **Da criacao, e nao de hoje.** E a correccao que da sentido ao campo:
        # com o prazo contado de hoje, empurrar o `expira_em` trinta dias para
        # a frente renovava a excepcao para sempre, com um diff de um
        # caractere. Agora prolongar exige mexer no `criado_em` — e, com ele,
        # na aprovacao e no autor, porque uma criacao nova e uma decisao nova.
        if (expira - criado).days > PRAZO_MAXIMO_DIAS:
            raise WaiverInvalido(
                f"{onde}: o prazo e de {(expira - criado).days} dias, contados de "
                f"`criado_em` ({criado.isoformat()}); o maximo e "
                f"{PRAZO_MAXIMO_DIAS}. Para prolongar, crie-o de novo: "
                "`criado_em`, `adr_ou_aprovacao` e `autor` novos."
            )

        validados.append({
            **waiver, "gate": gate,
            "criado_em": criado.isoformat(), "expira_em": expira.isoformat(),
        })

    return validados


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="ci_waivers", description="Valida ci/waivers.yaml"
    )
    analisador.add_argument("--root", type=Path, default=None)
    argumentos = analisador.parse_args(argv)
    raiz = (argumentos.root or Path(__file__).resolve().parent.parent).resolve()

    try:
        # Sem `raiz`: le o canon deste repositorio, e nao o do `--root`.
        verificar_cobertura_dos_gates()
        waivers = ler(raiz)
    except ConfiguracaoIlegivel as excepcao:
        # Codigo 2 e nao 1: o ficheiro nao se le, logo nao se sabe se ha achados.
        # E a mesma convencao dos outros nove consumidores do `kamba_yaml`.
        print(f"ci_waivers: erro de configuracao: {excepcao}", file=sys.stderr)
        return 2
    except WaiverInvalido as excepcao:
        print(f"ci_waivers: {excepcao}", file=sys.stderr)
        return 1

    if not waivers:
        print("ci_waivers: nenhuma excepcao activa")
        return 0

    hoje = _datetime.date.today()
    print(f"ci_waivers: {len(waivers)} excepcao(oes) activa(s)")
    for waiver in waivers:
        dias = (_datetime.date.fromisoformat(waiver["expira_em"]) - hoje).days
        print(
            f"  gate {waiver['gate']}  {waiver['alvo']}  "
            f"{waiver['adr_ou_aprovacao']}  expira em {dias} dia(s)  "
            f"({waiver['autor']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
