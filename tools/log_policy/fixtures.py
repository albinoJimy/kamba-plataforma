"""As *fixtures* do X-11: chamadas ao *logger* com dados pessoais em todo o lado.

Cada *fixture* e **uma chamada** descrita em JSON — nivel, argumentos
posicionais, campos e, nalgumas, um erro — e a lista dos seus **canarios**: as
cadeias que nao podem aparecer na saida. As duas linguagens leem o mesmo
ficheiro e fazem a mesma chamada (`conduzir.py` e
`packages/core-ts/tests/x11_conduzir.ts`), e a saida das duas tem de ser igual
byte a byte e nao conter canario nenhum.

Geram-se em vez de se guardarem: mil linhas com forma de telefone, de IBAN e de
token no repositorio eram mil coisas para o gate 9 e para um leitor desconfiar.
A geracao e determinista (`random.Random(semente)`), pelo que o ficheiro e o
mesmo em qualquer maquina.

As **classes** de canario e as **rotas** por onde entram estao fixas no codigo
(`CLASSES`, `ROTAS`), e o gerador recusa-se a produzir um conjunto em que
alguma combinacao falte: um varrimento que da zero porque as *fixtures* nao
tinham telefones passava pela razao errada.

Os formatos de NIF e de IBAN usados aqui sao **exemplos**, nao a definicao de
nenhum dos dois: o do NIF nao esta fixado em documento nenhum
(`docs/seguranca/lacunas.md`, Q-A).
"""

from __future__ import annotations

import base64
import random

SEMENTE = 68
QUANTAS = 1000

ALFANUMERICO = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _digitos(rng: random.Random, quantos: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(quantos))


def _alfa(rng: random.Random, quantos: int) -> str:
    return "".join(rng.choice(ALFANUMERICO) for _ in range(quantos))


def _uuid(rng: random.Random) -> str:
    h = "".join(rng.choice("0123456789abcdef") for _ in range(32))
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-a{h[17:20]}-{h[20:]}"


def _telefone(rng: random.Random) -> tuple[str, list[str]]:
    n = "9" + _digitos(rng, 8)
    formas = (
        f"+244 {n[:3]} {n[3:6]} {n[6:]}",
        f"+244{n}",
        f"244 {n[:3]} {n[3:6]} {n[6:]}",
        f"244{n}",
        f"00244{n}",
        n,
        f"{n[:3]} {n[3:6]} {n[6:]}",
        f"{n[:3]}-{n[3:6]}-{n[6:]}",
        f"{n[:3]}.{n[3:6]}.{n[6:]}",
        f"(+244) {n[:3]}-{n[3:6]}-{n[6:]}",
    )
    return rng.choice(formas), []


def _nif(rng: random.Random) -> tuple[str, list[str]]:
    # Exemplos de forma, NAO VERIFICADOS: dez digitos, e nove digitos com duas
    # letras e tres digitos.
    if rng.random() < 0.5:
        return _digitos(rng, 10), []
    return f"{_digitos(rng, 9)}{rng.choice('LBHK')}{rng.choice('AEO')}{_digitos(rng, 3)}", []


def _email(rng: random.Random) -> tuple[str, list[str]]:
    nome = rng.choice(("joaquina", "mateus", "esperanca", "nelson", "weza"))
    apelido = rng.choice(("canario", "cassule", "ndala", "sebastiao"))
    return f"{nome}.{apelido}{_digitos(rng, 3)}@exemplo.co.ao", []


def _texto(rng: random.Random) -> tuple[str, list[str]]:
    marca = f"CANARIO-TEXTO-{_digitos(rng, 5)}"
    frase = rng.choice(
        (
            "Bom dia, queria encomendar duas pizzas grandes para o Kilamba",
            "A minha encomenda ainda nao chegou, ja paguei ontem",
            "Marque-me para sabado as dez horas no salao da Maianga",
            "Transcricao: mana, manda o comprovativo que o mano ja transferiu",
        )
    )
    return f"{frase} [{marca}]", [marca]


def _nome(rng: random.Random) -> tuple[str, list[str]]:
    primeiro = rng.choice(("Joaquina", "Mateus", "Esperanca", "Nelson", "Weza"))
    marca = f"Canario{_digitos(rng, 4)}"
    return f"{primeiro} {marca} dos Santos", [marca]


def _morada(rng: random.Random) -> tuple[str, list[str]]:
    marca = f"Rua do Canario {_digitos(rng, 4)}"
    return f"{marca}, Bairro Operario, Luanda", [marca]


def _token(rng: random.Random) -> tuple[str, list[str]]:
    # Montados em tempo de execucao: nenhuma destas formas existe no repositorio.
    forma = rng.randrange(4)
    if forma == 0:
        return "EAA" + _alfa(rng, 64), []
    if forma == 1:
        return "Bearer " + _alfa(rng, 40), []
    if forma == 2:
        return ".".join(("eyJ" + _alfa(rng, 20), _alfa(rng, 30), _alfa(rng, 30))), []
    return "whk_" + _alfa(rng, 32), []


def _iban(rng: random.Random) -> tuple[str, list[str]]:
    corpo = _digitos(rng, 21)
    if rng.random() < 0.5:
        return f"AO06{corpo}", []
    grupos = " ".join(corpo[i : i + 4] for i in range(0, 21, 4))
    return f"AO06 {grupos}", []


def _referencia(rng: random.Random) -> tuple[str, list[str]]:
    forma = rng.randrange(4)
    if forma == 0:
        return _digitos(rng, 9), []
    if forma == 1:
        return f"{_digitos(rng, 5)} {_digitos(rng, 3)} {_digitos(rng, 3)} {_digitos(rng, 3)}", []
    if forma == 2:
        return f"evt_{_alfa(rng, 24)}", []
    return f"REF-{_digitos(rng, 12)}", []


def _wamid(rng: random.Random) -> tuple[str, list[str]]:
    """Um identificador com a forma dos da Meta: o telefone vai la dentro."""
    numero = "2449" + _digitos(rng, 8)
    bruto = bytes((0x1C, 0x18, len(numero))) + numero.encode("ascii") + bytes(
        rng.randrange(256) for _ in range(12)
    )
    valor = "wamid." + base64.b64encode(bruto).decode("ascii")
    return valor, [numero]


#: Classe de canario → gerador. A ordem e a de rotacao.
CLASSES = {
    "telefone": _telefone,
    "nif": _nif,
    "email": _email,
    "texto": _texto,
    "nome": _nome,
    "morada": _morada,
    "token": _token,
    "iban": _iban,
    "referencia": _referencia,
    "wamid": _wamid,
}

CAMPOS_DE_CHAMADA = (
    "tenant_id",
    "contact_hmac_prefix",
    "turn_id",
    "msg_id",
    "wa_type",
    "latency_ms",
    "tool",
    "outcome",
    "error_code",
)

CAMPOS_PROIBIDOS = (
    "telefone",
    "phone",
    "msisdn",
    "nome",
    "display_name",
    "morada",
    "texto",
    "text",
    "body",
    "transcricao",
    "email",
    "nif",
    "iban",
    "referencia",
    "provider_event_id",
    "Authorization",
    "X-Signature",
    "Cookie",
    "webhook_token",
    "headers",
    "extra",
    "contexto",
    "message",
    "msg",
)

#: Por onde um canario pode entrar numa chamada.
ROTAS = (
    "campo_conhecido",
    "campo_proibido",
    "chave",
    "aninhado",
    "lista",
    "posicional",
    "mensagem_de_erro",
    "classe_de_erro",
    "campo_reservado",
    "embutido",
    "codigo_de_erro",
)


def _base(rng: random.Random) -> dict:
    """Os campos legitimos que acompanham o canario."""
    return {
        "tenant_id": _uuid(rng),
        "outcome": rng.choice(("ok", "recusado", "erro", "tempo_esgotado")),
        "latency_ms": rng.randrange(0, 30_000),
    }


def _identificador_com(valor: str) -> str:
    """O canario dentro de algo com cara de identificador."""
    apenas = "".join(c if c.isalnum() else "_" for c in valor).strip("_").lower()
    return f"ok_{apenas}"[:60]


def _chamada(rng: random.Random, rota: str, valor: str, indice: int) -> dict:
    campos = _base(rng)
    posicionais: list = []
    erro = None
    codigo = None
    nivel = ("debug", "info", "warn", "error")[indice % 4]
    extra: list[str] = []

    if rota == "campo_conhecido":
        campo = CAMPOS_DE_CHAMADA[indice % len(CAMPOS_DE_CHAMADA)]
        campos[campo] = valor
    elif rota == "campo_proibido":
        campos[CAMPOS_PROIBIDOS[indice % len(CAMPOS_PROIBIDOS)]] = valor
    elif rota == "chave":
        campos[valor] = "ok"
    elif rota == "aninhado":
        alvo = ("contexto", "tool", "extra", "outcome")[indice % 4]
        campos[alvo] = {"headers": {"Authorization": valor}, "corpo": {"de": valor}}
    elif rota == "lista":
        alvo = ("error_code", "mensagens", "wa_type")[indice % 3]
        campos[alvo] = ["ok", valor, {"texto": valor}]
    elif rota == "posicional":
        posicionais = [valor] if indice % 2 else [valor, {"de": valor}]
    elif rota == "mensagem_de_erro":
        erro = {"classe": "ValueError", "mensagem": f"falhou ao tratar {valor}"}
        codigo = "callback_invalido"
    elif rota == "classe_de_erro":
        classe = "E" + "".join(c for c in valor if c.isalnum())[:40]
        erro = {"classe": classe, "mensagem": "sem conteudo"}
        codigo = "callback_invalido"
        extra.append(classe)
    elif rota == "campo_reservado":
        campos[("ts", "level", "svc")[indice % 3]] = valor
    elif rota == "embutido":
        embutido = _identificador_com(valor)
        campos[("outcome", "tool", "wa_type", "error_code")[indice % 4]] = embutido
        extra.append(embutido)
    elif rota == "codigo_de_erro":
        erro = {"classe": "RuntimeError", "mensagem": "sem conteudo"}
        codigo = valor
    else:  # pragma: no cover - a lista de rotas e fechada
        raise ValueError(rota)

    return {
        "nivel": nivel,
        "posicionais": posicionais,
        "campos": campos,
        "erro": erro,
        "codigo": codigo,
        "_extra": extra,
    }


#: Rotas em que o canario entra **transformado** em identificador: sem
#: pontuacao, em minusculas, colado a um prefixo. O que o *logger* ve ai ja nao
#: e o canario, e o que tem de recusar e o identificador construido.
ROTAS_TRANSFORMADAS = ("classe_de_erro", "embutido")

#: Classes cujo canario tem sempre sete ou mais digitos, e que por isso sao
#: recusadas mesmo depois de transformadas. As outras **nao** percorrem as rotas
#: transformadas: um nome ou uma frase passados a `snake_case` tem a forma de
#: um identificador legitimo, e o *logger* nao os distingue — limite declarado
#: em `docs/logs.md` §7, e nao uma *fixture* que fingisse prova-lo.
CLASSES_COM_DIGITOS = ("telefone", "nif", "iban")


def gerar(quantas: int = QUANTAS, semente: int = SEMENTE) -> list[dict]:
    """As *fixtures*, sempre as mesmas para a mesma semente."""
    rng = random.Random(semente)
    classes = list(CLASSES)
    rotas_directas = [r for r in ROTAS if r not in ROTAS_TRANSFORMADAS]
    fixtures: list[dict] = []
    for indice in range(quantas):
        classe = classes[indice % len(classes)]
        # A rota avanca com outro passo, para que as combinacoes classe × rota
        # se percorram todas em vez de andarem a par.
        # A classe roda a cada *fixture* e a rota a cada volta das classes: em
        # `len(CLASSES) * len(ROTAS)` *fixtures* passa-se por todos os pares.
        volta = indice // len(classes)
        rota = ROTAS[volta % len(ROTAS)]
        if rota in ROTAS_TRANSFORMADAS and classe not in CLASSES_COM_DIGITOS:
            rota = rotas_directas[(volta + indice) % len(rotas_directas)]
        valor, marcas = CLASSES[classe](rng)
        chamada = _chamada(rng, rota, valor, indice)
        extra = chamada.pop("_extra")

        canarios = list(marcas)
        if rota in ROTAS_TRANSFORMADAS:
            canarios.extend(extra)
        else:
            canarios.append(valor)
        fixtures.append(
            {
                "id": indice,
                "classe": classe,
                "rota": rota,
                # O valor tal como nasceu, antes de a rota o transformar: e o
                # que o controlo positivo do varrimento tem de ver.
                "valor": valor,
                "canarios": [c for c in canarios if len(c) >= 6],
                "chamada": chamada,
            }
        )
    _exigir_cobertura(fixtures)
    return fixtures


#: Quantas *fixtures* de forma se juntam as da rotacao.
EXTRAS = 30

#: As tres rotas das *fixtures* de forma.
ROTAS_DE_FORMA = ("numero", "identificador_ma_forma", "segredo_com_forma")


def gerar_extras(semente: int = SEMENTE, primeiro_id: int = QUANTAS) -> list[dict]:
    """*Fixtures* de **forma**: o que a rotacao de canarios nao exercita.

    As mil da rotacao poem canarios (cadeias) em todos os sitios; quase todos
    sao recusados logo pelo alfabeto do campo. Ficavam por exercitar tres
    regras, que a primeira revisao adversarial mutou sem o X-11 dar por isso
    (`docs/analises/ANALISE-11`, §6): o tecto de `latency_ms` (um telefone como
    **inteiro**), a forma por palavras dos identificadores (digitos pelo meio,
    sem chegar aos sete), e as formas de segredo que cabem no alfabeto de
    `error_code`. Cada valor e o seu proprio canario.
    """
    rng = random.Random(semente * 1000 + 7)
    campos_de_texto = ("outcome", "tool", "wa_type", "error_code")
    extras: list[dict] = []
    for indice in range(EXTRAS):
        rota = ROTAS_DE_FORMA[indice % len(ROTAS_DE_FORMA)]
        campos = _base(rng)
        if rota == "numero":
            numero = int("9" + _digitos(rng, 8))
            valor = str(numero)
            campos["latency_ms"] = numero
        elif rota == "identificador_ma_forma":
            # Letra, digito, letra, digito…: seis digitos no total, nunca dois
            # seguidos. Tem o alfabeto de um identificador e nao a forma.
            valor = "".join(
                rng.choice("bcdfghjkmnpqrstvwxz") + rng.choice("0123456789") for _ in range(6)
            ) + "".join(rng.choice("bcdfghjkmnpqrstvwxz") for _ in range(4))
            campos[campos_de_texto[(indice // 3) % len(campos_de_texto)]] = valor
        else:
            letras = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(18))
            if (indice // 3) % 2:
                valor = "sessao_invalida:eyJ" + letras
            else:
                valor = "EAA" + letras.upper()
            campos["error_code"] = valor
        extras.append(
            {
                "id": primeiro_id + indice,
                "classe": "forma",
                "rota": rota,
                "valor": valor,
                "canarios": [valor],
                "chamada": {
                    "nivel": ("debug", "info", "warn", "error")[indice % 4],
                    "posicionais": [],
                    "campos": campos,
                    "erro": None,
                    "codigo": None,
                },
            }
        )
    return extras


def _exigir_cobertura(fixtures: list[dict]) -> None:
    if len(fixtures) < len(CLASSES) * len(ROTAS):
        return  # um conjunto pequeno, pedido de proposito por um teste
    vistas = {(f["classe"], f["rota"]) for f in fixtures}
    em_falta = [
        (classe, rota)
        for classe in CLASSES
        for rota in ROTAS
        if (classe, rota) not in vistas
        and (rota not in ROTAS_TRANSFORMADAS or classe in CLASSES_COM_DIGITOS)
    ]
    if em_falta:
        raise AssertionError(
            f"as fixtures nao cobrem {len(em_falta)} combinacoes de classe e rota"
        )
