"""Validador dos artefactos do KAM-065 (docs/seguranca/).

Uso, da raiz do repositorio: python docs/seguranca/validar.py .

Verifica, por execucao e nao por leitura:
  matriz   colunas constantes, sem celulas vazias, dominios fechados, todo o
           KAM/ADR citado existe, todo o caminho e todo o teste citado existe
  stride   16 componentes x 6 categorias, celulas unicas, cada uma com teste
           existente ou ticket existente
  dpia     numero de operacoes e campos preenchidos
  docs     em todos os .md de docs/seguranca e na ANALISE-06: KAM, ADR,
           caminhos, testes, L-NN e RR-NN citados existem; sem padroes de
           telefone

Sai com 0 se nao houver nada a dizer, e com 1 se houver erros ou se a
configuracao estiver incompleta. **Nunca com um traceback** por causa de uma
contagem: ver «A guarda» abaixo.

## Limitacao declarada: tres das quatro familias nao tem fonte nesta arvore

Este repositorio e **publico**. Os artefactos que descrevem *o que ainda nao
esta protegido* — a matriz de conformidade, o modelo de ameacas STRIDE, a DPIA,
as lacunas e os riscos residuais — ficaram fora desta copia por decisao do
fundador (KAM-156, Outubro 2026): publicar a lista das portas abertas e entregar
o mapa antes de as fechar. O que ficou publico foi o **procedimento** (resposta
a incidentes, exercicio de simulacao, contactos, modelos de notificacao).

A consequencia para este validador e que as familias `matriz`, `stride` e `dpia`
**nao tem entrada** aqui. Ele nao finge que as verificou: reporta-as como **erro
de configuracao**, a nomear a fonte que falta. A familia `docs` corre a serio.

## A guarda, e porque nao e um `assert` com a contagem do canon

Ate ao KAM-149 a linha 43 era:

    assert len(KAM) == 138 and len(ADR) == 20 and len(DEC) == 13, (...)

Tres defeitos num so sitio. O numero **afirmava o presente**, pelo que
envelhecia a cada ticket novo; estava **antes** das quatro familias, pelo que o
programa abortava sem verificar nada; e abortava com uma **excepcao**, que para
quem nao le o traceback e indistinguivel de uma ferramenta que nao tem nada a
dizer. Desde que o backlog passou de 138, nenhuma execucao chegou as
verificacoes.

O que aquele `assert` protegia, e que **nao se perde**, era o caso de uma
expressao regular deixar de bater e os conjuntos virem vazios: ai todas as
verificacoes de existencia passariam por nao terem com que comparar. Isso agora
e uma **propriedade** — conjunto vazio, ou abaixo de um piso manifestamente
baixo — reportada como erro de configuracao com mensagem.

**Um piso nao e uma contagem.** `len(KAM) == 138` afirma o presente e deixa de
ser verdade amanha. `len(KAM) >= 10` afirma «manifestamente mais do que isto,
sempre», e continua verdadeiro enquanto o canon crescer. O piso nao e 1 porque
uma regex meio quebrada devolve um punhado e nao zero — e um punhado passaria um
teste de «nao vazio».

O `assert "\r" not in bruto` da matriz **mantem-se**: e uma propriedade, nao uma
contagem.
"""
import csv
import glob
import io
import os
import re
import sys

RAIZ = sys.argv[1] if len(sys.argv) > 1 else "."
SEG = os.path.join(RAIZ, "docs", "seguranca")
erros = []
notas = []
#: Problemas de configuracao: uma fonte que falta ou que veio vazia. Separados
#: dos `erros` de proposito — um erro e um defeito no conteudo verificado, e um
#: problema de configuracao e a verificacao a nao ter podido acontecer. Juntar
#: os dois fazia um relatorio dizer «3 erros» quando o que havia era uma fonte
#: em falta e nenhuma verificacao feita.
config = []


def ler(caminho):
    with io.open(os.path.join(RAIZ, caminho), encoding="utf-8") as f:
        return f.read()


def erro(msg):
    erros.append(msg)


def problema_de_configuracao(msg):
    config.append(msg)


#: Marca, no corpo de um artefacto, que ele nao vive nesta copia. E a mesma
#: cadeia que os sete esbocos do KAM-156 trazem na primeira linha.
MARCA_DE_ESBOCO = "nao vive neste repositorio"


def e_esboco(caminho):
    """O ficheiro existe mas e o aviso de que o conteudo esta noutro sitio.

    Apanha tambem o `UnicodeDecodeError`, que **nao** e um `OSError`: com so
    `except OSError` aqui, um `.md` que nao fosse UTF-8 passava por esta funcao e
    levantava, depois de o `ler_ou_nada` da familia `docs` ja o ter reportado em
    paz. Achado 3 da revisao adversarial, caso 12.
    """
    try:
        return MARCA_DE_ESBOCO in ler(caminho)
    except (OSError, UnicodeDecodeError):
        return False


def fonte_utilizavel(caminho, familia):
    """Ha conteudo a verificar em `caminho`? Se nao, diz porque, e nao mente."""
    alvo = os.path.join(RAIZ, caminho)
    if not os.path.exists(alvo):
        problema_de_configuracao(
            "%s: a fonte %s nao existe nesta arvore" % (familia, caminho)
        )
        return False
    if e_esboco(caminho):
        problema_de_configuracao(
            "%s: %s e um esboco (%r) — o conteudo vive em albinoJimy/kamba "
            "(privado), no mesmo caminho; esta familia NAO foi verificada"
            % (familia, caminho, MARCA_DE_ESBOCO)
        )
        return False
    return True


# ------------------------------------------------------------ fontes canonicas
#
# Lidas com `ler_ou_nada`: um ficheiro ausente, ilegivel ou que nao seja UTF-8 e
# um **erro de configuracao**, nunca uma excepcao. Sem isto, um `INDICE.md`
# ausente dava `FileNotFoundError` antes da primeira familia — a mesma forma de
# falha do `assert` que este ticket corrigiu, com outro nome. Achado 3 da revisao
# adversarial.
def ler_ou_nada(caminho, familia):
    """O conteudo, ou `None` com o motivo registado. Nunca levanta."""
    try:
        return ler(caminho)
    except FileNotFoundError:
        problema_de_configuracao("%s: a fonte %s nao existe" % (familia, caminho))
    except IsADirectoryError:
        problema_de_configuracao("%s: %s e uma pasta e nao um ficheiro" % (familia, caminho))
    except UnicodeDecodeError as erro_de_leitura:
        problema_de_configuracao(
            "%s: %s nao e UTF-8 (%s)" % (familia, caminho, erro_de_leitura.reason)
        )
    except OSError as erro_de_leitura:
        problema_de_configuracao(
            "%s: %s nao se consegue ler (%s)"
            % (familia, caminho, type(erro_de_leitura).__name__)
        )
    return None


indice = ler_ou_nada("specs/INDICE.md", "canon") or ""
KAM = set(re.findall(r"^\| (KAM-\d{3}) \|", indice, re.M))
arq = ler_ou_nada("docs/tecnica/00_Arquitectura_Solucao.md", "canon") or ""
ADR = set(re.findall(r"^\| \*{0,2}(ADR-\d{3})\*{0,2} \|", arq, re.M))
DEC = set(re.findall(r"^\| (D\d{1,2}) \|", arq, re.M))

#: Pisos manifestamente baixos, muito abaixo de qualquer valor plausivel. Nao
#: sao contagens do canon e nao se actualizam quando ele cresce: so disparam se
#: a regex de cima deixar de bater. Ver «A guarda» na docstring.
PISOS = (
    ("KAM", KAM, 10, "specs/INDICE.md §4"),
    ("ADR", ADR, 5, "docs/tecnica/00_Arquitectura_Solucao.md §8"),
    ("DEC", DEC, 5, "docs/tecnica/00_Arquitectura_Solucao.md §13.3"),
)
for _nome, _conjunto, _piso, _fonte in PISOS:
    if not _conjunto:
        problema_de_configuracao(
            "canon: o conjunto %s veio VAZIO de %s — a expressao regular deixou "
            "de bater. Sem ele, toda a verificacao de existencia passaria por "
            "nao ter com que comparar." % (_nome, _fonte)
        )
    elif len(_conjunto) < _piso:
        problema_de_configuracao(
            "canon: o conjunto %s tem %d entradas, abaixo do piso %d, lido de "
            "%s — a expressao regular bate mal. Nao e uma contagem do canon: e "
            "um piso que so dispara se a leitura se quebrar."
            % (_nome, len(_conjunto), _piso, _fonte)
        )

#: As lacunas e os riscos residuais sao fonte **e** alvo: as familias conferem
#: que todo o `L-NN` e `RR-NN` citado existe. Nesta arvore os dois sao esbocos,
#: pelo que os conjuntos vem vazios — e um conjunto vazio aqui nao faz as
#: verificacoes passarem: fa-las **saltar**, declaradamente. Com elas a correr
#: contra um conjunto vazio, qualquer `L-20` citado num documento verdadeiro
#: dava «lacuna inexistente», que e um erro inventado pela fonte em falta e nao
#: um defeito do documento.
LAC, RR = set(), set()
LAC_UTILIZAVEL = fonte_utilizavel("docs/seguranca/lacunas.md", "lacunas")
if LAC_UTILIZAVEL:
    LAC = set(re.findall(r"^\| (L-\d{2}) \|", ler("docs/seguranca/lacunas.md"), re.M))
    if not LAC:
        problema_de_configuracao(
            "lacunas: docs/seguranca/lacunas.md nao e esboco mas nao rendeu "
            "nenhum L-NN — a expressao regular deixou de bater"
        )
        LAC_UTILIZAVEL = False
RR_UTILIZAVEL = fonte_utilizavel("docs/seguranca/riscos_residuais.md", "riscos")
if RR_UTILIZAVEL:
    RR = set(
        re.findall(r"^\| (RR-\d{2}) \|", ler("docs/seguranca/riscos_residuais.md"), re.M)
    )
    if not RR:
        problema_de_configuracao(
            "riscos: docs/seguranca/riscos_residuais.md nao e esboco mas nao "
            "rendeu nenhum RR-NN — a expressao regular deixou de bater"
        )
        RR_UTILIZAVEL = False

EXT = r"(?:py|ts|md|yaml|yml|json|json5|csv|sh|toml|ini|cjs|mako)"
RE_CAMINHO = re.compile(
    r"(?<![\w/.-])((?:\.\./)*(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\." + EXT + r")(?![\w/-])"
)
RE_TESTE = re.compile(r"([A-Za-z0-9_./-]+\.(?:py|ts))::([^;|`]+)")
RE_KAM = re.compile(r"(?<![A-Za-z0-9-])(KAM|ADR)-(\d{3,4})(?![0-9])")
RE_TEL = re.compile(r"\+244[\s\d]{6,}|(?<!\d)9\d{8}(?!\d)")

# Caminhos que se citam de proposito sem existirem: entregas futuras de outros
# tickets, nomeadas como tal no texto. Cada um e declarado aqui, nao dispensado
# por padrao.
#
# Duas entradas do original sairam porque **passaram a existir** nesta arvore
# (`docs/evidencia/KAM-024.md` e `docs/isolamento.md`): uma dispensa que ja nao
# dispensa nada e uma porta aberta que ninguem vigia.
FUTUROS = {
    "docs/tecnica/evidencia/validacao/Pacote_Parecer_Juridico.md",
    # KAM-083, aberto. O `docs/seguranca/resposta_incidentes.md` cita-o e diz, na
    # mesma frase, «(ainda nao existe)»; o que esta em
    # `docs/runbooks/RB-K10-incidente-de-seguranca.md` e um **esboco do KAM-080**
    # que declara no cabecalho que o runbook completo e o KAM-083. Logo e entrega
    # futura nomeada como tal, que e exactamente o que esta lista cobre — e nao um
    # caminho atrasado.
    "ops/runbooks/RB-K10.md",
}


def existe_caminho(c, base):
    if c in FUTUROS:
        return True
    for raiz in (RAIZ, os.path.join(RAIZ, base)):
        if os.path.exists(os.path.normpath(os.path.join(raiz, c))):
            return True
    return False


def existe_teste(caminho, nome):
    alvo = os.path.join(RAIZ, caminho)
    if not os.path.exists(alvo):
        return False
    try:
        corpo = io.open(alvo, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError):
        # Um ficheiro de teste ilegivel nao e um teste que exista.
        return False
    nome = nome.strip().strip("`").strip()
    if caminho.endswith(".py"):
        return re.search(r"def " + re.escape(nome) + r"\(", corpo) is not None
    return nome in corpo


# Numero de criterios de aceitacao de cada bloco `## KAM-NNN` dos epics, para
# conferir que um `KAM-NNN CA n` citado cabe no bloco.
N_CA = {}
for _f in sorted(glob.glob(os.path.join(RAIZ, "specs", "EPIC-*.md"))):
    _cur, _sec = None, ""
    for _l in io.open(_f, encoding="utf-8"):
        _m = re.match(r"^## (KAM-\d{3}) ", _l)
        if _m:
            _cur, _sec = _m.group(1), ""
            N_CA[_cur] = 0
        elif _l.startswith("## "):
            _cur = None
        elif _l.startswith("### "):
            _sec = _l
        elif (
            _cur
            and _sec.startswith("### Critérios")
            and (_l.startswith("- [") or re.match(r"^\| AC-\d+ ", _l))
        ):
            N_CA[_cur] += 1
citacoes_ca = [0]


def verificar_ca(texto, onde):
    for m in re.finditer(r"(KAM-\d{3}) (CA ?\d+(?:(?:, | e | a )(?:CA ?)?\d+)*)", texto):
        for n in re.findall(r"\d+", m.group(2)):
            citacoes_ca[0] += 1
            if int(n) < 1 or int(n) > N_CA.get(m.group(1), 0):
                erro(
                    "%s: %s CA %s nao existe (o bloco tem %d criterios)"
                    % (onde, m.group(1), n, N_CA.get(m.group(1), 0))
                )


def verificar_refs(texto, onde, base):
    verificar_ca(texto, onde)
    for m in RE_KAM.finditer(texto):
        ident = "%s-%s" % (m.group(1), m.group(2))
        if ident not in KAM and ident not in ADR:
            erro("%s: referencia inexistente %s" % (onde, ident))
    for m in RE_TESTE.finditer(texto):
        if not existe_teste(m.group(1), m.group(2)):
            erro("%s: teste inexistente %s::%s" % (onde, m.group(1), m.group(2).strip()))
    for m in RE_CAMINHO.finditer(texto):
        if not existe_caminho(m.group(1), base):
            erro("%s: caminho inexistente %s" % (onde, m.group(1)))
    # As duas verificacoes seguintes **saltam** sem a fonte, em vez de inventar
    # erros. O salto fica no relatorio, para nao se ler como «conferido».
    if LAC_UTILIZAVEL:
        for ident in re.findall(r"(?<![A-Za-z0-9-])(L-\d{2})(?![0-9])", texto):
            if ident not in LAC:
                erro("%s: lacuna inexistente %s" % (onde, ident))
    if RR_UTILIZAVEL:
        for ident in re.findall(r"(?<![A-Za-z0-9-])(RR-\d{2})(?![0-9])", texto):
            if ident not in RR:
                erro("%s: risco inexistente %s" % (onde, ident))
    if RE_TEL.search(texto):
        erro("%s: padrao de telefone" % onde)


# ---------------------------------------------------------------------- matriz
#
# As colunas, os vocabularios fechados e a forma. Sao **estrutura**, e ja sao
# publicos: os codigos de componente vivem em `docs/tecnica/`, e os papeis nas
# tabelas de aprovacao dos epics.
#
# O que **nao** esta aqui, e e deliberado: as series de identificadores de
# linha, a lista dos ADR que a matriz tem de cobrir, e os termos que o STRIDE
# e a DPIA exigem nomear. Cada um desses literais codifica um **achado** — que
# ameacas existem, que entradas nao sao confiaveis, que operacoes tocam dados
# pessoais — e nao a forma do artefacto. Num repositorio publico, cuja historia
# e para sempre, essa diferenca e a que importa. Ficam devolvidos ao fundador
# na seccao de verificacao do bloco do KAM-149.
OBRIG = [
    "id", "origem", "controlo", "componente", "ticket", "teste_id", "dono",
    "fase", "estado_evidencia", "juridico", "criterio_saida",
]
DONOS = {"SEG", "AP", "RP", "PRIV", "OPS", "T&S", "ADV"}
#: Os componentes, **lidos da arquitectura** e nao escritos aqui.
#:
#: O original tinha duas listas a mao, no mesmo ficheiro, com conteudos
#: diferentes — 17 nomes na da matriz e 16 na do STRIDE — e **nenhuma** das duas
#: tinha o `ENT` nem o `GEO`, que o `docs/tecnica/00` ja define. Isso e a classe
#: de defeito deste ticket numa instancia mais fraca: um literal no codigo a
#: afirmar o estado presente de um canon que cresce. O modo de falha era
#: silencioso e dos dois lados — uma linha da matriz com `componente = ENT` dava
#: «componente desconhecido» falso, e o STRIDE nunca esperava as celulas dos
#: componentes novos, pelo que elas ficavam invisiveis em vez de em falta.
#:
#: Agora derivam da fonte, com a lista a mao como recurso declarado se a leitura
#: se quebrar — e a quebra e reportada. Achado 7 da revisao adversarial.
COMP_DE_RECURSO = (
    "GWY", "CHR", "AGR", "REG", "TLS", "HND", "COM", "PAY", "IDX", "EVT", "TEN",
    "LLM", "MED", "STO", "OBS", "GOV", "DAT",
)
def _codigos_de_componente(texto):
    """Os codigos da tabela de componentes, pelo maior bloco contiguo.

    Nao se filtra por lista de excepcoes: o `| ADR | Decisao | ... |` de outra
    tabela do mesmo documento tambem casa o padrao de uma linha de tres letras,
    e uma lista de nomes a excluir era outra afirmacao a envelhecer. O que
    distingue a tabela certa e ser **a maior corrida de linhas seguidas** dessa
    forma, e isso nao precisa de manutencao.
    """
    blocos, actual, anterior = [], [], None
    for n, linha in enumerate(texto.splitlines()):
        m = re.match(r"^\| \*{0,2}([A-Z]{3})\*{0,2} \|", linha)
        if m and (anterior is None or n == anterior + 1):
            actual.append(m.group(1))
            anterior = n
        elif m:
            blocos.append(actual)
            actual, anterior = [m.group(1)], n
    blocos.append(actual)
    return sorted(set(max(blocos, key=len))) if blocos else []


_componentes = _codigos_de_componente(arq)
#: Piso da mesma familia dos outros: so dispara se a leitura se quebrar.
MINIMO_DE_COMPONENTES = 10
if len(_componentes) < MINIMO_DE_COMPONENTES:
    problema_de_configuracao(
        "componentes: a arquitectura rendeu %d codigos de componente, abaixo do "
        "piso %d — a expressao regular deixou de bater. A verificacao de "
        "componente e a forma do STRIDE usam a lista de recurso do codigo, que "
        "pode estar atrasada." % (len(_componentes), MINIMO_DE_COMPONENTES)
    )
    _componentes = list(COMP_DE_RECURSO)
COMP = set(_componentes)
ESTADOS = {"CONFIRMADO", "INDÍCIO", "NÃO VERIFICADO"}
CONTROLO = {"existe-testado", "existe-nao-testado", "nao-existe", "parcial", "sem-ticket"}

MATRIZ = "docs/seguranca/matriz_conformidade.csv"
if not fonte_utilizavel(MATRIZ, "matriz"):
    print("MATRIZ  sem fonte nesta arvore — NAO verificada (ver erros de configuracao)")
else:
    with io.open(os.path.join(RAIZ, MATRIZ), encoding="utf-8", newline="") as f:
        bruto = f.read()
    assert "\r" not in bruto, "CRLF na matriz"
    linhas = [r for r in csv.reader(io.StringIO(bruto)) if r and not r[0].startswith("#")]
    if not linhas:
        # Sem esta guarda, `linhas[0]` dava `IndexError` num CSV vazio ou feito
        # so de comentarios. Achado 3 da revisao adversarial, casos 8 e 9.
        problema_de_configuracao(
            "matriz: %s nao tem nenhuma linha fora dos comentarios — nem cabecalho" % MATRIZ
        )
        linhas = [[]]
    cab, corpo = linhas[0], linhas[1:]
    if cab[: len(OBRIG)] != OBRIG:
        erro(
            "matriz: as %d primeiras colunas nao sao as do criterio: %s"
            % (len(OBRIG), cab[: len(OBRIG)])
        )
    # Piso de linhas, da mesma familia dos `PISOS` do canon: uma matriz com
    # cabecalho certo e duas linhas nao e uma matriz de conformidade, e sem isto
    # passava com «0 erros». Nao e uma contagem — e um limite inferior monotono,
    # muito abaixo de qualquer valor plausivel. Achado 2 da revisao adversarial.
    MINIMO_DE_LINHAS = 20
    if not corpo:
        problema_de_configuracao(
            "matriz: %s tem cabecalho e ZERO linhas de dados — nada a verificar" % MATRIZ
        )
    elif len(corpo) < MINIMO_DE_LINHAS:
        problema_de_configuracao(
            "matriz: %s tem %d linhas de dados, abaixo do piso %d — fonte oca ou "
            "truncada. Nao e uma contagem da matriz: e um piso que so dispara se a "
            "fonte se degradar" % (MATRIZ, len(corpo), MINIMO_DE_LINHAS)
        )
    ids = []
    contagem = {}
    for n, r in enumerate(corpo, start=2):
        if len(r) != len(cab):
            erro("matriz L%d: %d colunas, esperadas %d" % (n, len(r), len(cab)))
            continue
        d = dict(zip(cab, r))
        ids.append(d["id"])
        for k, v in d.items():
            if not v.strip():
                erro("matriz %s: celula vazia em %s" % (d["id"], k))
        for p in d["dono"].split("/"):
            if p not in DONOS:
                erro("matriz %s: dono fora do vocabulario: %s" % (d["id"], p))
        for c in d["componente"].split():
            if c not in COMP:
                erro("matriz %s: componente desconhecido: %s" % (d["id"], c))
        if d["fase"] not in {"P", "C", "D"}:
            erro("matriz %s: fase %s" % (d["id"], d["fase"]))
        if d["estado_evidencia"] not in ESTADOS:
            erro("matriz %s: estado %s" % (d["id"], d["estado_evidencia"]))
        if d["juridico"] not in {"sim", "não"}:
            erro("matriz %s: juridico %s" % (d["id"], d["juridico"]))
        estado_controlo = d.get("estado_controlo", d["controlo"])
        if estado_controlo not in CONTROLO:
            erro("matriz %s: estado_controlo %s" % (d["id"], estado_controlo))
        contagem[estado_controlo] = contagem.get(estado_controlo, 0) + 1
        # Sem a fonte das lacunas, `LAC` vem vazio — e entao um `L-NN` escrito
        # nestas duas colunas daria «ticket invalido», que e um erro inventado
        # pela fonte em falta e nao um defeito da matriz. E a mesma propriedade
        # do criterio 3 deste ticket, do outro lado: um conjunto vazio nao pode
        # mudar o significado de uma verificacao em silencio. Sem ela, a parte
        # `L-NN` **salta**, e o salto ja esta declarado nos erros de
        # configuracao.
        toks = d["ticket"].split()
        for t in toks:
            if t in KAM:
                continue
            if re.fullmatch(r"L-\d{2}", t):
                if LAC_UTILIZAVEL and t not in LAC:
                    erro("matriz %s: lacuna inexistente na coluna ticket: %s" % (d["id"], t))
                continue
            erro("matriz %s: ticket invalido %s" % (d["id"], t))
        tem_teste = any(existe_teste(a, b) for a, b in RE_TESTE.findall(d["teste_id"]))
        tem_ticket = any(
            ("KAM-%s" % x) in KAM for x in re.findall(r"KAM-(\d{3})", d["teste_id"])
        )
        # Sem a fonte, uma lacuna citada conta como citada: o que nao se pode
        # conferir nao se da por errado.
        lacunas_citadas = re.findall(r"L-\d{2}", d["teste_id"])
        tem_lacuna = any(
            (x in LAC if LAC_UTILIZAVEL else True) for x in lacunas_citadas
        )
        if not (tem_teste or tem_ticket or tem_lacuna):
            erro("matriz %s: teste_id sem ficheiro, ticket nem lacuna" % d["id"])
        if estado_controlo in ("existe-testado", "parcial") and not tem_teste:
            erro("matriz %s: controlo dado como existente sem teste com caminho" % d["id"])
        verificar_refs(" | ".join(r), "matriz %s" % d["id"], "docs/seguranca")
    if len(ids) != len(set(ids)):
        erro("matriz: ids repetidos")
    print("MATRIZ  %d linhas x %d colunas" % (len(corpo), len(cab)))
    print("        estado_controlo:", dict(sorted(contagem.items())))

# ---------------------------------------------------------------------- stride
#
# A forma: 16 componentes x 6 categorias = 96 celulas unicas. O numero 96 nao e
# uma contagem do canon — e o produto de duas listas que estao aqui, e muda se
# e so se uma delas mudar.
#: A **mesma** lista da matriz, e nao uma segunda escrita a mao: era assim que
#: as duas divergiam (17 contra 16) no mesmo ficheiro. O numero de celulas
#: esperadas passa a derivar da fonte, pelo que um componente novo na
#: arquitectura aparece como celula **em falta** em vez de ficar invisivel.
COMPS = sorted(COMP)
CATEGORIAS = "STRIDE"
STRIDE_MD = "docs/seguranca/ameacas_stride.md"
if not fonte_utilizavel(STRIDE_MD, "stride"):
    print(
        "STRIDE  sem fonte nesta arvore — NAO verificadas as %d celulas "
        "esperadas (%d componentes x %d categorias)"
        % (len(COMPS) * len(CATEGORIAS), len(COMPS), len(CATEGORIAS))
    )
else:
    stride = ler(STRIDE_MD)
    celulas = {}
    for m in re.finditer(
        r"^\| ((?:%s)-[%s]) \|(.*)$" % ("|".join(COMPS), CATEGORIAS), stride, re.M
    ):
        if m.group(1) in celulas:
            erro("stride: celula repetida %s" % m.group(1))
        celulas[m.group(1)] = m.group(2)
    esperadas = ["%s-%s" % (c, k) for c in COMPS for k in CATEGORIAS]
    if not celulas:
        problema_de_configuracao(
            "stride: %s nao e esboco mas nao rendeu nenhuma celula das %d "
            "esperadas — a expressao regular deixou de bater"
            % (STRIDE_MD, len(esperadas))
        )
    falta = [c for c in esperadas if c not in celulas]
    if falta:
        erro("stride: celulas em falta: %s" % falta)
    sem_nada, com_teste = [], 0
    for ident, resto in celulas.items():
        campos = [c.strip() for c in resto.split("|")]
        if len(campos) < 5 or any(not c for c in campos[:4]):
            erro("stride %s: campo vazio" % ident)
        t = any(existe_teste(a, b) for a, b in RE_TESTE.findall(resto))
        k = any(("KAM-%s" % x) in KAM for x in re.findall(r"KAM-(\d{3})", resto))
        if t:
            com_teste += 1
        if not (t or k):
            sem_nada.append(ident)
    print(
        "STRIDE  %d celulas unicas de %d esperadas; com teste existente: %d"
        % (len(celulas), len(esperadas), com_teste)
    )
    if sem_nada:
        erro("stride: celulas sem teste nem ticket: %s" % sem_nada)
    # Propriedade, nao conteudo: «tem um diagrama» nao diz que ameacas existem.
    # Estava no original, saiu na primeira versao deste ficheiro sem ser
    # declarada, e volta. Achado da revisao adversarial.
    if "flowchart" not in stride:
        erro("stride: sem diagrama")

# ------------------------------------------------------------------------ dpia
#
# `MINIMO_DE_OPERACOES` e um piso da mesma familia dos `PISOS` do canon: um
# minimo que nao envelhece. Os **nomes** das operacoes nao estao aqui, por
# serem conteudo.
MINIMO_DE_OPERACOES = 6
DPIA_MD = "docs/seguranca/dpia_simplificada.md"
if not fonte_utilizavel(DPIA_MD, "dpia"):
    print(
        "DPIA    sem fonte nesta arvore — NAO verificadas as operacoes "
        "(minimo %d)" % MINIMO_DE_OPERACOES
    )
else:
    dpia = ler(DPIA_MD)
    ops = re.findall(r"^\| (O-\d{2}) \|(.*)$", dpia, re.M)
    #: Numero minimo de colunas por operacao. Com o `[:-1]` do original e uma
    #: linha `| O-NN |` sem campos, `campos` fica vazio e `any(...)` sobre uma
    #: lista vazia e `False`: seis linhas nuas passavam a familia com ZERO erros.
    #: Achado 2 e nota da revisao adversarial.
    MINIMO_DE_COLUNAS = 4
    for ident, resto in ops:
        campos = [c.strip() for c in resto.split("|")][:-1]
        if len(campos) < MINIMO_DE_COLUNAS:
            erro(
                "dpia %s: %d coluna(s), menos do que as %d minimas"
                % (ident, len(campos), MINIMO_DE_COLUNAS)
            )
            continue
        if any(not c for c in campos):
            erro("dpia %s: campo vazio" % ident)
    print(
        "DPIA    %d operacoes (minimo %d); colunas por operacao: %s"
        % (len(ops), MINIMO_DE_OPERACOES, sorted({len(r.split("|")) - 1 for _, r in ops}))
    )
    if len(ops) < MINIMO_DE_OPERACOES:
        erro("dpia: menos de %d operacoes" % MINIMO_DE_OPERACOES)

# ------------------------------------------------------------------------ docs
#
# Esta familia corre a serio nesta arvore: os ficheiros .md de docs/seguranca
# existem e tem texto, esbocos incluidos — um esboco e um documento curto, nao
# um ficheiro vazio, e as referencias que ele faz tem de resolver como as
# outras.
# **Recursivo**, ao contrario do original: o `os.listdir` nao descia a
# `docs/seguranca/modelos/`, pelo que os tres modelos de notificacao — 99, 82 e
# 81 linhas de documento real, que nem sao esbocos — nunca eram varridos, e o
# «N ficheiros verificados» lia-se como cobertura que nao havia. Achado 8 da
# revisao adversarial.
alvos = sorted(
    (os.path.join(dir_, f).replace("\\", "/")[len(RAIZ) + 1:]
     if dir_.startswith(RAIZ) else os.path.join(dir_, f).replace("\\", "/"))
    for dir_, _sub, ficheiros in os.walk(SEG)
    for f in ficheiros
    if f.endswith(".md")
)
_analises = os.path.join(RAIZ, "docs", "analises")
if os.path.isdir(_analises):
    alvos += [
        "docs/analises/" + f
        for f in sorted(os.listdir(_analises))
        if f.startswith("ANALISE-06")
    ]
for a in alvos:
    t = ler_ou_nada(a, "docs")
    if t is None:
        continue
    verificar_refs(t, a.replace("\\", "/"), os.path.dirname(a))
    # Um esboco e um aviso de duas duzias de linhas e nao um documento do
    # conjunto: exigir-lhe controlo de versoes era exigir-lhe que fingisse ser
    # o que ele diz nao ser.
    if "Controlo de versões" not in t and not e_esboco(a):
        erro("%s: sem controlo de versoes" % a)
print("DOCS    %d ficheiros .md verificados (KAM, ADR, caminhos, testes, telefones)" % len(alvos))
print("        dos quais esbocos, sem conteudo proprio a verificar: %d"
      % sum(1 for a in alvos if e_esboco(a)))
print("        citacoes 'KAM-NNN CA n' conferidas contra o numero de criterios do bloco: %d"
      % citacoes_ca[0])
if LAC_UTILIZAVEL:
    print("        lacunas definidas: %d" % len(LAC))
else:
    print("        L-NN: NAO conferidos — a fonte das lacunas nao esta nesta arvore")
if RR_UTILIZAVEL:
    print("        riscos definidos: %d" % len(RR))
else:
    print("        RR-NN: NAO conferidos — a fonte dos riscos nao esta nesta arvore")
print("        canon lido: KAM %d, ADR %d, DEC %d" % (len(KAM), len(ADR), len(DEC)))
for n in notas:
    print("        " + n)

# ----------------------------------------------------------------- o relatorio
#
# Os dois blocos sao separados e os dois fazem sair com 1. Um erro de
# configuracao nao e um erro de conteudo: juntar os dois fazia o relatorio dizer
# «6 erros» quando o que ha e uma fonte em falta e cinco familias nao medidas.
#
# **O que a guarda das fontes evita nao e um «0 erros» falso — e a ausencia de
# relatorio.** Medido: o validador anterior, corrido contra esta arvore com o
# `assert` da linha 43 relaxado, morria com `KeyError: 'id'` na familia da
# matriz (o esboco comeca por linhas de comentario, pelo que o cabecalho lido
# nao tem a coluna `id`) e imprimia **zero** linhas. Nao havia limpo falso a
# evitar: nao havia saida nenhuma. Ver `docs/evidencia/KAM-149.md` §2.
if config:
    print("\nERROS DE CONFIGURACAO (%d) — verificacao incompleta:" % len(config))
    for c in config:
        print("  -", c)
if erros:
    print("\nERROS (%d):" % len(erros))
    for e in erros:
        print("  -", e)
if config or erros:
    print(
        "\nRESUMO: %d erro(s) de conteudo, %d problema(s) de configuracao"
        % (len(erros), len(config))
    )
    sys.exit(1)
print("\nOK: 0 erros")
