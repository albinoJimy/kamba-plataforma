"""O corpus sintetico PT-AO da minimizacao (KAM-112, criterios 3 e 4).

O criterio 3 pede «>= 300 casos etiquetados (0 dados reais)» com recall por tipo;
o criterio 4 pede «>= 200 casos adversariais» com **0** precos, totais,
quantidades, horas ou `sku` alterados. Este modulo e o corpus, e os casos sao
**dados** e nao asercoes: o `test_minimizacao.py` corre-os e publica as medidas.

A forma e a do `casos_adversariais.py` (KAM-032), e nao e imitacao — e a mesma
licao, pela mesma razao:

`COM_PII`    cada caso diz **que** identificadores tem e **quais**. Nao basta
             mascarar algo: um detector que mascarasse o texto inteiro dava
             «recall 100%» e nao valia nada. O que se mede e se **aquele** valor
             foi substituido.

`NUMEROS`    o controlo do criterio 4, e e tambem o controlo **positivo** do
             corpus de PII: cada caso diz que cadeias tem de sobreviver
             **literalmente**. Sem ele, «0 precos alterados» era satisfeito por
             um detector que nao mascarasse nada — e `assertNotIn` sobre PII em
             300 casos era satisfeito por um que mascarasse tudo. Os dois
             conjuntos juntos e que fecham a tenaz: um impede o detector de ser
             surdo, o outro impede-o de ser cego.

`LIMITES`    casos que o detector **nao** apanha, e que apanharia se a garantia
             fosse absoluta. Nao sao falhas a corrigir neste ticket: sao o risco
             residual que o bloco declara («nomes proprios em texto livre e
             referencias a locais escapam a regras; a minimizacao **reduz** a
             exposicao mas nao prova que deixou de haver transferencia»). Estao
             aqui para ficarem **medidos** em vez de esquecidos, e **nao entram
             na contagem do recall**.

## Zero dados reais, e e um requisito com nome

Nada aqui veio de uma conversa. Os telefones sao numeros construidos digito a
digito, os nomes sao nomes comuns, os bairros sao toponimos publicos, os e-mails
usam `exemplo.co.ao`. O Termos da Meta §4.7 proibe usar dados da plataforma para
treinar ou melhorar ML (ADR-018, `docs/tecnica/evidencia/E1_Meta_WhatsApp.md`
§4), e um corpus construido a partir de mensagens de clientes era exactamente
isso — a montante de qualquer modelo, porque este corpus **calibra** o detector.

## A regra dos tres, escrita onde o resultado aparece

0 falhas em N = 200 limita o risco a aproximadamente **1,5%** com 95% de
confianca. «0 numeros alterados neste conjunto» **nao** e «0 numeros alterados em
producao»: os limiares do criterio 3 e a sobrecarga do criterio 7 sao
***propostas a calibrar no Piloto*** (KAM-109), e quem citar os numeros deste
corpus cita tambem esta frase.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Final

# ---------------------------------------------------------------- as formas

#: Telefones moveis angolanos **sinteticos**. Todos comecam por 9, que e o movel
#: (o mesmo que o `packages/core-ts/src/eventos/pii.ts` fixa), e nenhum e de
#: ninguem: foram escritos digito a digito.
NUMEROS_SINTETICOS: Final = (
    "912345678",
    "923456789",
    "934567890",
    "945678901",
    "956789012",
    "967890123",
    "978901234",
    "989012345",
    "991234567",
    "900111222",
    "913579246",
    "924680135",
    "935791468",
    "946802579",
    "992468013",
    "903691472",
)

#: Os digitos arabes-indicos, para o caso «digitos Unicode» do criterio 2. O
#: `dicionarios.dobrar` reduz cada um ao ASCII pelo `unicodedata.digit`, sem
#: tabela nossa.
_UNICODE: Final = "٠١٢٣٤٥٦٧٨٩"

#: Os digitos por extenso, na forma que alguem dita um numero.
_EXTENSO: Final = ("zero", "um", "dois", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove")


def _unicode(numero: str) -> str:
    """O mesmo numero com digitos arabes-indicos."""
    return "".join(_UNICODE[int(digito)] for digito in numero)


def _extenso(numero: str) -> str:
    """O mesmo numero ditado por extenso."""
    return " ".join(_EXTENSO[int(digito)] for digito in numero)


def _grupos(numero: str, separador: str) -> str:
    """`912345678` -> `912 345 678` com o separador dado."""
    return separador.join((numero[:3], numero[3:6], numero[6:]))


#: As dez formas de escrever um movel que o criterio 2 enumera, cada uma uma
#: funcao do numero. O nome da forma entra no nome do caso, para que um vermelho
#: diga **qual** forma falhou e nao «o telefone falhou».
FORMAS_DE_TELEFONE: Final = (
    ("nu", lambda n: n),
    ("espacos", lambda n: _grupos(n, " ")),
    ("pontos", lambda n: _grupos(n, ".")),
    ("hifenes", lambda n: _grupos(n, "-")),
    ("mais244", lambda n: f"+244 {_grupos(n, ' ')}"),
    ("mais244_junto", lambda n: f"+244{n}"),
    ("zerozero244", lambda n: f"00244{n}"),
    ("prefixo_nu", lambda n: f"244 {_grupos(n, ' ')}"),
    ("unicode", _unicode),
    ("extenso", _extenso),
)

#: Moldes de frase em que um telefone aparece. Em PT-AO, e sem acentos no codigo
#: pela convencao do repositorio.
MOLDES_DE_TELEFONE: Final = (
    "o meu numero e {}",
    "liga ao {}",
    "pode mandar mensagem para o {}",
    "contacto: {}",
    "fala comigo pelo {}",
)

#: Bairros e municipios que **estao** no dicionario do detector, com o molde.
MOLDES_DE_MORADA: Final = (
    "entregar em {}",
    "moro no {}",
    "a entrega e no {}",
    "perto do {}",
    "estou na {}",
)

LOCAIS_DO_CORPUS: Final = (
    "Maianga",
    "Ingombota",
    "Rangel",
    "Sambizanga",
    "Cassenda",
    "Alvalade",
    "Miramar",
    "Viana",
    "Cacuaco",
    "Talatona",
    "Kilamba",
    "Camama",
    "Benfica",
    "Golfe",
    "Nova Vida",
    "Vila Alice",
    "Morro Bento",
    "Rocha Pinto",
    "Hoji ya Henda",
    "Bairro Operario",
    "Prenda",
    "Maculusso",
    "Mutamba",
    "Palanca",
    "Zango",
    "Patriota",
    "Corimba",
    "Terra Nova",
    "Catambor",
    "Belas",
)

#: Nomes proprios com apelido, para a regra do par, e nomes sozinhos com gatilho.
NOMES_DO_CORPUS: Final = (
    ("Joao", "Silva"),
    ("Maria", "Gourgel"),
    ("Pedro", "Neto"),
    ("Ana", "Pereira"),
    ("Jose", "Van-Dunem"),
    ("Isabel", "Fernandes"),
    ("Carlos", "Sousa"),
    ("Teresa", "Lopes"),
    ("Manuel", "Chicoti"),
    ("Rosa", "Kiluanje"),
    ("Augusto", "Bengui"),
    ("Beatriz", "Rodrigues"),
    ("Domingos", "Gomes"),
    ("Helena", "Monteiro"),
    ("Francisco", "Alves"),
    ("Catarina", "Ribeiro"),
)

MOLDES_DE_PESSOA: Final = (
    "fala com o {}",
    "pergunta ao {}",
    "o pedido e para a {}",
    "diz ao {} que ja paguei",
    "entregar ao {}",
)

#: Dominios sinteticos. `exemplo.co.ao` e `exemplo.com` nao sao de ninguem.
DOMINIOS: Final = ("exemplo.co.ao", "exemplo.com", "loja.exemplo.ao", "mail.exemplo.co.ao")

#: Prefixos de BSUID. O criterio 2 escreve `PT.`; as *fixtures* deste
#: repositorio usam `AO.` (`packages/core-ts/tests/identity.cripto.test.ts`).
#: Entram os dois — ver a nota do `detector.BSUID_PADRAO`.
PREFIXOS_DE_BSUID: Final = ("PT.", "AO.")

CORPOS_DE_BSUID: Final = (
    "a1b2c3d4e5",
    "x9k2m4p8q1",
    "zz00aa11bb",
    "k7j6h5g4f3",
    "m2n3b4v5c6",
    "q1w2e3r4t5",
    "y6u7i8o9p0",
    "l9k8j7h6g5",
    "d4s3a2z1x0",
    "n5m6b7v8c9",
)

#: O padrao do NIF com que o corpus se mede. ***NAO E CANON.***
#:
#: O `docs/tecnica/08` nao define o formato do NIF angolano e o bloco do KAM-112
#: manda **nao o inventar**. Este padrao e um **parametro de medicao**, com a
#: mesma funcao do `make x11 X11_NIF='<regex>'` do KAM-068, que resolveu a mesma
#: ausencia no mesmo documento: serve para que o recall de NIF seja **mensuravel**
#: em vez de ser 0% por ausencia de padrao, e diz em voz alta que foi medido com
#: um padrao de ensaio.
#:
#: A forma escolhida — dez digitos, ou nove digitos e uma letra final — e a que o
#: corpus usa para gerar os casos, pelo que a medicao e consistente por
#: construcao. **Nao se afirma que e o formato angolano**: isso e NAO VERIFICADO,
#: e quem souber o formato passa o seu.
PADRAO_DE_NIF_DE_ENSAIO: Final = re.compile(r"(?<![0-9])\d{9}[0-9a-z](?![0-9a-z])")

#: NIF sinteticos que casam o `PADRAO_DE_NIF_DE_ENSAIO`.
NIFS_SINTETICOS: Final = (
    "5417238690",
    "5000987651",
    "0061234567",
    "5412345678",
    "5498765432",
    "5403691472",
    "5013579246",
    "0072468013",
    "5424680135",
    "5435791468",
)

MOLDES_DE_NIF: Final = (
    "o meu NIF e {}",
    "factura com o NIF {}",
    "NIF: {}",
)


# ---------------------------------------------------------------- os tipos


@dataclasses.dataclass(frozen=True, slots=True)
class CasoDePii:
    """Um caso do corpus de PII: o texto e **que valores** tem de ser mascarados.

    O `espera` e uma tupla de `(tipo, valor)`. O valor e a cadeia **exacta** que
    aparece no texto, e e isso que torna a medicao honesta: o que se verifica e
    que *aquele* pedaco deixou de estar la, nao que algo mudou.
    """

    nome: str
    texto: str
    espera: tuple[tuple[str, str], ...]
    familia: str


@dataclasses.dataclass(frozen=True, slots=True)
class CasoDeNumero:
    """Um caso adversarial do criterio 4: que cadeias **tem** de sobreviver.

    O `intactos` e o que tem de continuar no texto minimizado, caracter a
    caracter. Um caso pode ter varias (um preco e uma hora na mesma frase).
    """

    nome: str
    texto: str
    intactos: tuple[str, ...]
    familia: str


@dataclasses.dataclass(frozen=True, slots=True)
class Limite:
    """Um caso que o detector **nao** apanha, declarado em vez de escondido."""

    nome: str
    texto: str
    #: O que la fica e que, com uma garantia absoluta, nao ficaria.
    escapa: str
    razao: str


# ---------------------------------------------------------------- COM_PII


def _com_pii() -> tuple[CasoDePii, ...]:
    casos: list[CasoDePii] = []

    # --- telefone: dez formas x dez numeros, em cinco moldes a rodar.
    #
    # **Cem casos de telefone, e e o tipo com mais**: e o identificador mais
    # comum numa conversa de comercio e o que tem mais formas de ser escrito. O
    # molde roda com o indice para que nenhuma forma fique presa a uma frase.
    for indice, numero in enumerate(NUMEROS_SINTETICOS):
        for forma, escrever in FORMAS_DE_TELEFONE:
            escrito = escrever(numero)
            molde = MOLDES_DE_TELEFONE[indice % len(MOLDES_DE_TELEFONE)]
            casos.append(
                CasoDePii(
                    nome=f"telefone_{forma}_{numero}",
                    texto=molde.format(escrito) + ".",
                    espera=(("TELEFONE", escrito),),
                    familia="telefone",
                )
            )

    # --- morada: vinte locais em cinco moldes a rodar, mais vinte com o
    #     toponimo sozinho (o dicionario basta, sem gatilho).
    for indice, local in enumerate(LOCAIS_DO_CORPUS):
        molde = MOLDES_DE_MORADA[indice % len(MOLDES_DE_MORADA)]
        casos.append(
            CasoDePii(
                nome=f"morada_com_gatilho_{local.replace(' ', '_')}",
                texto=molde.format(local) + ", por favor.",
                espera=(("MORADA", local),),
                familia="morada",
            )
        )
        casos.append(
            CasoDePii(
                nome=f"morada_sem_gatilho_{local.replace(' ', '_')}",
                texto=f"A loja do {local} tem isso?",
                espera=(("MORADA", local),),
                familia="morada",
            )
        )

    # --- pessoa: o par (sem gatilho) e o nome sozinho (com gatilho).
    for indice, (nome, apelido) in enumerate(NOMES_DO_CORPUS):
        casos.append(
            CasoDePii(
                nome=f"pessoa_par_{nome}_{apelido}",
                texto=f"A encomenda e da {nome} {apelido} e ja foi paga.",
                espera=(("PESSOA", f"{nome} {apelido}"),),
                familia="pessoa",
            )
        )
        molde = MOLDES_DE_PESSOA[indice % len(MOLDES_DE_PESSOA)]
        casos.append(
            CasoDePii(
                nome=f"pessoa_com_gatilho_{nome}",
                texto=molde.format(nome) + ".",
                espera=(("PESSOA", nome),),
                familia="pessoa",
            )
        )

    # --- e-mail: nomes locais x dominios.
    locais_de_email = (
        "joao.silva", "maria", "pedro_neto", "ana-pereira", "loja",
        "encomendas", "isabel.f", "c.sousa",
    )
    for indice, local in enumerate(locais_de_email):
        for dominio in DOMINIOS:
            endereco = f"{local}@{dominio}"
            casos.append(
                CasoDePii(
                    nome=f"email_{local}_{dominio}",
                    texto=f"Manda para {endereco}, obrigado."
                    if indice % 2 == 0
                    else f"O meu e-mail e {endereco}.",
                    espera=(("EMAIL", endereco),),
                    familia="email",
                )
            )

    # --- BSUID: dois prefixos x cinco corpos.
    for prefixo in PREFIXOS_DE_BSUID:
        for corpo in CORPOS_DE_BSUID:
            bsuid = f"{prefixo}{corpo}"
            casos.append(
                CasoDePii(
                    nome=f"bsuid_{prefixo.rstrip('.')}_{corpo}",
                    texto=f"O identificador do WhatsApp e {bsuid}.",
                    espera=(("BSUID", bsuid),),
                    familia="bsuid",
                )
            )

    # --- NIF: cinco numeros em tres moldes.
    for indice, nif in enumerate(NIFS_SINTETICOS):
        for molde in MOLDES_DE_NIF:
            casos.append(
                CasoDePii(
                    nome=f"nif_{nif}_{indice}_{MOLDES_DE_NIF.index(molde)}",
                    texto=molde.format(nif) + ".",
                    espera=(("NIF", nif),),
                    familia="nif",
                )
            )

    # --- mistos: PII **e** numeros de negocio na mesma frase, que e a forma
    #     real de uma mensagem e o caso que exercita a tenaz dos dois criterios.
    mistos = (
        (
            "misto_telefone_e_preco",
            "Liga ao 912345678, o total e 12.500 Kz.",
            (("TELEFONE", "912345678"),),
        ),
        (
            "misto_morada_e_hora",
            "Entregar no Maianga as 15h30.",
            (("MORADA", "Maianga"),),
        ),
        (
            "misto_pessoa_preco_quantidade",
            "Fala com o Joao: sao 2 x 3.500 Kz.",
            (("PESSOA", "Joao"),),
        ),
        (
            "misto_tudo",
            "Fala com a Maria Gourgel, entrego no Golfe as 9h, 2x500 Kz, "
            "o meu numero e 923456789 e o e-mail maria@exemplo.co.ao.",
            (
                ("PESSOA", "Maria Gourgel"),
                ("MORADA", "Golfe"),
                ("TELEFONE", "923456789"),
                ("EMAIL", "maria@exemplo.co.ao"),
            ),
        ),
        (
            "misto_dois_telefones",
            "Os meus numeros sao 912345678 e 923456789.",
            (("TELEFONE", "912345678"), ("TELEFONE", "923456789")),
        ),
        (
            "misto_telefone_e_sku",
            "Quero o sku ABC-123 e liga ao 934567890.",
            (("TELEFONE", "934567890"),),
        ),
        (
            "misto_bsuid_e_total",
            "O meu BSUID e AO.a1b2c3d4e5 e o total 45.000 Kz.",
            (("BSUID", "AO.a1b2c3d4e5"),),
        ),
        (
            "misto_email_e_percentagem",
            "Manda a factura para loja@exemplo.com com 20% de desconto.",
            (("EMAIL", "loja@exemplo.com"),),
        ),
    )
    for nome, texto, espera in mistos:
        casos.append(CasoDePii(nome=nome, texto=texto, espera=espera, familia="misto"))

    return tuple(casos)


#: O corpus de PII. >= 300 casos etiquetados, 0 dados reais (criterio 3).
COM_PII: Final = _com_pii()


# ---------------------------------------------------------------- NUMEROS


def _numeros() -> tuple[CasoDeNumero, ...]:
    casos: list[CasoDeNumero] = []

    # --- precos: os valores que um catalogo angolano tem, nas formas em que se
    #     escrevem, com a moeda dos dois lados.
    valores = (
        "12.500", "1.750", "45.000", "2.500", "350", "99.999", "1.000.000",
        "12 500", "7,50", "250,00", "3.499", "15.000", "800", "64.900",
        "120.000", "999", "5.250", "18.750", "2.000.000", "73.410",
        "4.999", "32.000", "1.499", "87.650", "6.300", "210.000", "55",
        "9.750", "148.200", "2.875",
    )
    moedas = ("Kz", "kz", "AOA", "kwanzas")
    for indice, valor in enumerate(valores):
        moeda = moedas[indice % len(moedas)]
        casos.append(
            CasoDeNumero(
                nome=f"preco_depois_{valor}_{moeda}",
                texto=f"O total e {valor} {moeda}.",
                intactos=(valor,),
                familia="preco",
            )
        )
        casos.append(
            CasoDeNumero(
                nome=f"preco_antes_{valor}_{moeda}",
                texto=f"Custa {moeda} {valor} a unidade.",
                intactos=(valor,),
                familia="preco",
            )
        )

    # --- **os que parecem telefone**, que e o caso que o bloco nomeia por
    #     extenso: «um total de nove digitos ao lado de Kz que parece telefone».
    #
    #     Cada um destes e, caracter a caracter, um movel angolano valido. Se o
    #     detector os mascarar, o produto perde o total da encomenda — e o
    #     criterio 4 chama a isso 0 alterados.
    parecem_telefone = (
        "912500000", "923456789", "934567890", "945678901", "956789012",
        "967890123", "978901234", "989012345", "991234567", "900111222",
    )
    for numero in parecem_telefone:
        casos.append(
            CasoDeNumero(
                nome=f"total_parece_telefone_{numero}",
                texto=f"O total da encomenda e {numero} Kz.",
                intactos=(numero,),
                familia="preco_que_parece_telefone",
            )
        )
        pontuado = ".".join((numero[:3], numero[3:6], numero[6:]))
        casos.append(
            CasoDeNumero(
                nome=f"total_pontuado_parece_telefone_{numero}",
                texto=f"Fica em {pontuado} Kz, tudo incluido.",
                intactos=(pontuado,),
                familia="preco_que_parece_telefone",
            )
        )
        casos.append(
            CasoDeNumero(
                nome=f"total_moeda_antes_parece_telefone_{numero}",
                texto=f"Kz {numero} e o total.",
                intactos=(numero,),
                familia="preco_que_parece_telefone",
            )
        )

    # --- quantidades com multiplicador, que o criterio nomeia («2 x 3.500»).
    quantidades = (
        ("2 x 3.500", ("2 x 3.500",)),
        ("3 x 250", ("3 x 250",)),
        ("10x1.200", ("10x1.200",)),
        ("2x500", ("2x500",)),
        ("5 x 99", ("5 x 99",)),
        ("12 x 1.000", ("12 x 1.000",)),
        ("1 x 45.000", ("1 x 45.000",)),
        ("4x2.250", ("4x2.250",)),
        ("6 x 750", ("6 x 750",)),
        ("20 x 300", ("20 x 300",)),
        ("8 x 1.250", ("8 x 1.250",)),
        ("15x80", ("15x80",)),
        ("7 x 3.000", ("7 x 3.000",)),
        ("30 x 150", ("30 x 150",)),
        ("2 x 12.500", ("2 x 12.500",)),
    )
    for escrito, intactos in quantidades:
        casos.append(
            CasoDeNumero(
                nome=f"quantidade_{escrito.replace(' ', '_')}",
                texto=f"Quero {escrito}, por favor.",
                intactos=intactos,
                familia="quantidade",
            )
        )
        casos.append(
            CasoDeNumero(
                nome=f"quantidade_com_moeda_{escrito.replace(' ', '_')}",
                texto=f"Sao {escrito} Kz no total.",
                intactos=intactos,
                familia="quantidade",
            )
        )

    # --- unidades.
    unidades = (
        "2 kg", "500 g", "1,5 l", "750 ml", "3 unidades", "12 caixas",
        "2 duzias", "6 garrafas", "24 latas", "1 pack",
        "10 kg", "250 ml", "2 pares", "5 sacos", "18 unidades", "3 fardos",
    )
    for escrito in unidades:
        casos.append(
            CasoDeNumero(
                nome=f"unidade_{escrito.replace(' ', '_').replace(',', '')}",
                texto=f"Leva {escrito}.",
                intactos=(escrito,),
                familia="unidade",
            )
        )

    # --- horas, que o criterio nomeia («as 15h30»).
    horas = (
        "15h30", "9h", "14:00", "08h15", "18h45", "7h30", "12:30", "21h",
        "10h00", "16:15", "6h45", "23h59",
        "11h20", "17:45", "13h10", "20h05",
    )
    for escrito in horas:
        casos.append(
            CasoDeNumero(
                nome=f"hora_{escrito.replace(':', 'h')}",
                texto=f"Marcamos as {escrito} na loja.",
                intactos=(escrito,),
                familia="hora",
            )
        )
        casos.append(
            CasoDeNumero(
                nome=f"hora_com_preco_{escrito.replace(':', 'h')}",
                texto=f"As {escrito}, por 2.500 Kz.",
                intactos=(escrito, "2.500"),
                familia="hora",
            )
        )

    # --- `sku`, que o criterio nomeia.
    skus = (
        "ABC-123", "SKU-912345678", "XPT-0001", "A1B2C3", "REF-2026-45",
        "P100", "MOD-77X", "CX-12/450", "TV55-4K", "KZ-9001",
        "FRG-220L", "SAP42-PT", "ART-00912", "LT-5/250", "BIC-3UN",
    )
    for sku in skus:
        casos.append(
            CasoDeNumero(
                nome=f"sku_{sku.replace('/', '_')}",
                texto=f"Quero o {sku}.",
                intactos=(sku,),
                familia="sku",
            )
        )
        casos.append(
            CasoDeNumero(
                nome=f"sku_com_preco_{sku.replace('/', '_')}",
                texto=f"O {sku} custa 15.000 Kz.",
                intactos=(sku, "15.000"),
                familia="sku",
            )
        )

    # --- datas e percentagens.
    for escrito in ("12/03", "12-03-2026", "01/01/2027", "28/02", "15-08-2026"):
        casos.append(
            CasoDeNumero(
                nome=f"data_{escrito.replace('/', '_').replace('-', '_')}",
                texto=f"A promocao e de {escrito} em diante.",
                intactos=(escrito,),
                familia="data",
            )
        )
    for escrito in ("20%", "5%", "12,5%", "100%", "7 %"):
        casos.append(
            CasoDeNumero(
                nome=f"percentagem_{escrito.replace('%', 'pc').replace(' ', '').replace(',', '')}",
                texto=f"Tem {escrito} de desconto.",
                intactos=(escrito,),
                familia="percentagem",
            )
        )

    # --- frases **inteiras** de comercio, com varios numeros de cada tipo. Sao
    #     o caso mais parecido com o que um cliente escreve, e por isso os que
    #     mais valem.
    reais = (
        (
            "real_pedido_completo",
            "Quero 2 x 3.500 Kz de agua e 1 pack de 6 garrafas, total 7.000 Kz, "
            "entrego as 15h30 do dia 12/03 com 10% de desconto.",
            ("2 x 3.500", "1 pack", "6 garrafas", "7.000", "15h30", "12/03", "10%"),
        ),
        (
            "real_total_grande",
            "O total da factura e 1.250.000 Kz, com 14% de IVA, referencia REF-2026-45.",
            ("1.250.000", "14%", "REF-2026-45"),
        ),
        (
            "real_tres_linhas",
            "3 x 250 Kz, 2 x 1.500 Kz e 1 x 45.000 Kz dao 48.250 Kz.",
            ("3 x 250", "2 x 1.500", "1 x 45.000", "48.250"),
        ),
        (
            "real_horario",
            "Abrimos das 8h as 18h, sabado das 9h as 13h.",
            ("8h", "18h", "9h", "13h"),
        ),
        (
            "real_stock",
            "Tenho 912345678 unidades em stock, ao preco de 350 Kz cada.",
            ("912345678", "350"),
        ),
        (
            "real_peso_e_preco",
            "O saco de 25 kg custa 18.750 Kz, o de 50 kg sai a 35.000 Kz.",
            ("25 kg", "18.750", "50 kg", "35.000"),
        ),
    )
    for nome, texto, intactos in reais:
        casos.append(
            CasoDeNumero(nome=nome, texto=texto, intactos=intactos, familia="real")
        )

    return tuple(casos)


#: Os casos adversariais de numeros de negocio. >= 200, com 0 alterados
#: (criterio 4). E tambem o controlo positivo do corpus de PII.
NUMEROS: Final = _numeros()


# ---------------------------------------------------------------- LIMITES

#: O que este detector **nao** apanha, declarado. **Nao entra no recall.**
#:
#: Sao as limitacoes que o bloco do KAM-112 escreve por extenso («nomes proprios
#: em texto livre e referencias a locais escapam a regras») mais as que a
#: construcao deste detector acrescenta. Cada uma com a razao, para que a
#: proxima auditoria nao as pague outra vez.
LIMITES: Final = (
    Limite(
        nome="telefone_colado_a_moeda",
        texto="O meu numero e 912345678 Kz",
        escapa="912345678",
        razao=(
            "o marcador de moeda reclama o numero como preco (criterio 4) e o "
            "detector nunca o ve. E o lado certo de errar — mascarar um preco "
            "destroi o produto — e e o custo medido do desenho que da «0 precos "
            "alterados» por construcao. Um cliente teria de escrever «Kz» a "
            "seguir ao proprio telefone"
        ),
    ),
    Limite(
        nome="fixo_angolano",
        texto="Liga para o +244 222 123 456",
        escapa="222 123 456",
        razao=(
            "o criterio 2 enumera `+244 9XX XXX XXX` e `9XXXXXXXX` — o **movel** "
            "—, e o `pii.ts` deste repositorio fixa o mesmo (`\\+?244 ?9[0-9]{8}`). "
            "Um fixo nao esta no criterio; alargar o padrao a qualquer nono digito "
            "fazia qualquer sequencia de nove digitos virar telefone, e a colisao "
            "com totais ficava muito pior"
        ),
    ),
    Limite(
        nome="nome_proprio_sem_gatilho",
        texto="A Beatriz ja veio buscar",
        escapa="Beatriz",
        razao=(
            "e a limitacao que o bloco declara. Um nome proprio capitalizado sem "
            "gatilho de pessoa e sem apelido nao se mascara, porque mascarar toda "
            "a palavra capitalizada fazia «Tenho Interesse Naquele Produto» dar "
            "quatro `PESSOA_n`. E a razao de o limiar de nomes ser 90% e nao 99%"
        ),
    ),
    Limite(
        nome="bairro_fora_do_dicionario",
        texto="Moro no Cazenga de cima, zona 18",
        escapa="de cima",
        razao=(
            "o dicionario de locais e conhecimento geral escrito a mao e NAO "
            "VERIFICADO (nao ha lista oficial no repositorio). O toponimo que "
            "esta na lista e mascarado; o qualificador que se lhe cola nao. "
            "Calibra-se no Piloto, KAM-109"
        ),
    ),
    Limite(
        nome="nif_sem_padrao",
        texto="O meu NIF e 5417238690",
        escapa="5417238690",
        razao=(
            "o `detector.PADRAO_DE_NIF` e `None` por omissao porque o "
            "`docs/tecnica/08` nao define o formato e o bloco manda nao o "
            "inventar. **Sem padrao passado, o recall de NIF e 0% por desenho** — "
            "e o precedente e o `make x11 X11_NIF` do KAM-068. O corpus mede-o "
            "com o `PADRAO_DE_NIF_DE_ENSAIO`, que e parametro de medicao e nao "
            "canon"
        ),
    ),
    Limite(
        nome="morada_descritiva",
        texto="Estou na terceira casa depois da bomba de gasolina",
        escapa="terceira casa depois da bomba de gasolina",
        razao=(
            "uma morada descrita sem toponimo nem numero nao tem forma nenhuma "
            "que uma regra apanhe. E a parte de «referencias a locais escapam a "
            "regras» que o bloco declara, e e tambem a razao por que a "
            "minimizacao **reduz** a exposicao e nao prova que ela deixou de "
            "existir (a confirmar por parecer)"
        ),
    ),
)


# ---------------------------------------------------------------- contagens


def quantos_por_tipo(casos: tuple[CasoDePii, ...] = COM_PII) -> dict[str, int]:
    """Quantos valores de cada tipo o corpus espera. O denominador do recall."""
    contagem: dict[str, int] = {}
    for caso in casos:
        for tipo, _valor in caso.espera:
            contagem[tipo] = contagem.get(tipo, 0) + 1
    return contagem
