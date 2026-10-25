"""Superficie 1 — migracoes: tabelas, colunas, valores de `CHECK`, esquemas, unicidades.

O SQL de uma revisao e obtido por `revisao.extrair` (leitura da arvore
sintactica, sem executar nada) e analisado por `sql.analisar`. Este modulo
junta os dois e aplica as regras do dicionario ao que saiu.

**Falha fechada**, em tres sitios:

* o que o leitor de revisoes nao segue (`revisao.py`) e achado `ilegivel`;
* uma instrucao SQL de forma desconhecida e achado `ilegivel`;
* uma coluna com dominio no dicionario que aparece num `CHECK` que nao se
  conseguiu ler (`estado SIMILAR TO …`), ou que e criada sem `CHECK` nenhum, e
  achado — o dominio do §3 nao se cumpre por omissao.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import revisao, sql
from .achados import FORA, ILEGIVEL, REGRA, Achado, aceita, fora, variante, variantes_em_texto
from .dicionario import Saber


@dataclass
class Contagem:
    instrucoes: int = 0
    tabelas: int = 0
    colunas: int = 0
    valores: int = 0
    opacos: int = 0

    def juntar(self, outra: "Contagem") -> None:
        self.instrucoes += outra.instrucoes
        self.tabelas += outra.tabelas
        self.colunas += outra.colunas
        self.valores += outra.valores
        self.opacos += outra.opacos


def _nivel1(tokens: list[sql.Token], desloca: int, ficheiro: str, saber: Saber, sufixo: str, achados: list[Achado]) -> None:
    """Variantes em **qualquer** token: identificadores, cadeias e corpos `$$`."""
    for token in tokens:
        linha = desloca + token.linha - 1
        encontradas = []
        if token.tipo == "ident":
            v = saber.variante_de_nome(token.valor) or saber.variante_de_nome(token.valor.lower())
            if v is not None:
                encontradas.append(v)
        elif token.tipo == "str":
            v = saber.variante_de_valor(token.valor)
            if v is not None:
                encontradas.append(v)
            # Uma chave de `jsonb`, um nome dentro de SQL dinamico, um comentario
            # de coluna: a variante esta la, so que entre plicas.
            encontradas += variantes_em_texto(saber, token.valor)
        elif token.tipo == "dollar":
            try:
                _nivel1(sql.tokenizar(token.valor), linha, ficheiro, saber, sufixo, achados)
            except sql.SqlIlegivel:
                for v in variantes_em_texto(saber, token.valor):
                    achados.append(variante(ficheiro, linha, v))
            continue
        for v in encontradas:
            achado = variante(ficheiro, linha, v)
            if sufixo:
                achado = Achado(achado.ficheiro, achado.linha, achado.classe, achado.mensagem + sufixo)
            achados.append(achado)


def _nivel2(objectos: sql.Objectos, ficheiro: str, saber: Saber) -> tuple[list[Achado], int]:
    """As regras do dicionario sobre tudo o que o ficheiro introduz."""
    achados: list[Achado] = []
    dicionario = saber.dicionario
    valores_lidos = 0

    for nome, linha in objectos.esquemas:
        if not saber.variante_de_nome(nome) and not aceita(saber, "esquema", nome):
            achados.append(fora(ficheiro, linha, "esquema", nome))
    for esquema, nome, linha in objectos.tabelas:
        if esquema and not saber.variante_de_nome(esquema) and not aceita(saber, "esquema", esquema):
            achados.append(fora(ficheiro, linha, "esquema", esquema))
        if not saber.variante_de_nome(nome) and not aceita(saber, "tabela", nome):
            achados.append(fora(ficheiro, linha, "tabela", nome))
    for tabela, coluna, linha in objectos.colunas:
        if saber.variante_de_nome(coluna):
            continue  # ja reportada no nivel 1
        if not aceita(saber, "coluna", f"{tabela}.{coluna}", simples=coluna):
            assinatura = dicionario.tabelas.get(tabela)
            contexto = (
                f"`{assinatura['assinatura']}`, dicionário §{assinatura['seccao']}" if assinatura else ""
            )
            achados.append(fora(ficheiro, linha, "coluna", f"{tabela}.{coluna}", contexto))
    for nome, linha in objectos.papeis:
        if not saber.variante_de_nome(nome) and not aceita(saber, "papel", nome):
            achados.append(fora(ficheiro, linha, "papel", nome))
    for nome, linha in objectos.tipos:
        if not saber.variante_de_nome(nome) and not aceita(saber, "tipo_sql", nome):
            achados.append(fora(ficheiro, linha, "tipo_sql", nome))

    # Um ENUM e o dominio fechado da coluna que o usa, tal como um `CHECK … IN`.
    checks = list(objectos.checks)
    for tabela, coluna, tipo, linha in objectos.tipos_de_coluna:
        for nome in tipo:
            if nome in objectos.enums:
                checks.append(sql.Check(tabela, coluna, objectos.enums[nome][0], True, linha))
    usados_por_coluna = {n for _, _, tipo, _ in objectos.tipos_de_coluna for n in tipo}
    for nome, (valores, linha) in objectos.enums.items():
        if nome not in usados_por_coluna:
            # Um ENUM que nenhuma coluna deste ficheiro usa: os valores so tem
            # de ser nomes conhecidos (a coluna pode vir noutra revisao).
            checks.append(sql.Check(nome, nome, valores, False, linha))

    com_dominio_lido: set[tuple[str, str]] = set()
    for check in checks:
        valores_lidos += len(check.valores)
        dominio = dicionario.dominio_de(check.tabela, check.coluna)
        alvo = f"{check.tabela}.{check.coluna}"
        if dominio:
            if check.fechado:
                com_dominio_lido.add((check.tabela, check.coluna))
            canonicos = list(dominio["valores"])
            sobra = [v for v in check.valores if v not in canonicos]
            # **`falta` nao se cobra a uma declaracao declarada historica.**
            #
            # Um dominio fechado pode crescer, e cresce por `DROP CONSTRAINT` +
            # `ADD CONSTRAINT` numa revisao posterior. A revisao antiga continua
            # a declarar o dominio antigo, que e um facto historico e nao um
            # defeito: a base, depois de `upgrade head`, tem o dominio novo.
            # Sem isto, **nenhum dominio fechado deste repositorio podia
            # crescer** — a revisao que o criou ficava sempre em falta, e a unica
            # saida era editar uma revisao ja fundida, coisa que aqui nunca se
            # fez (cada uma das 22 tem um `commit`, do seu proprio ticket).
            # Medido no KAM-029, o primeiro a fazer um crescer.
            #
            # A lista e **nomeada** e vive em `ci/canon-lint.yaml`
            # (`dominios_historicos`), com revisao, ticket, razao e data. **Nao
            # se infere da ordem dos ficheiros**: a primeira versao desta regra,
            # no mesmo ticket, fazia-o e tinha tres buracos que a revisao
            # adversarial demonstrou (`ANALISE-31`, achado 5) — a amnistia nao
            # exigia prova de `DROP CONSTRAINT` (pelo que um `ADD CONSTRAINT`
            # com nome novo **ao lado** do antigo deixava a base a recusar e o
            # gate a dizer conforme), o leitor de revisoes le o `downgrade` e uma
            # declaracao de la amnistiava as anteriores, e a ordem era o
            # `sorted()` do caminho e nao a cadeia de revisoes.
            #
            # O `sobra` **continua a cobrar-se sempre**: um valor que o
            # dicionario ja nao tem e achado em qualquer revisao, historica ou
            # nao, porque nenhuma base devia aceitar o que o canon esqueceu.
            historica = any(
                entrada.revisao == ficheiro
                and entrada.tabela == check.tabela
                and entrada.coluna == check.coluna
                for entrada in saber.politica.dominios_historicos
            )
            falta = (
                [v for v in canonicos if v not in check.valores]
                if check.fechado and not historica
                else []
            )
            if sobra or falta:
                pormenor = "; ".join(
                    p
                    for p in (
                        f"falta: {', '.join(falta)}" if falta else "",
                        f"a mais: {', '.join(sobra)}" if sobra else "",
                    )
                    if p
                )
                achados.append(
                    Achado(
                        ficheiro,
                        check.linha,
                        REGRA,
                        f"`{alvo}` com {{{', '.join(check.valores)}}} → "
                        f"`{', '.join(canonicos)}`, dicionário §{dominio['seccao']} ({pormenor})",
                    )
                )
            continue
        for valor in check.valores:
            if saber.variante_de_valor(valor):
                continue  # ja reportada no nivel 1
            if not aceita(saber, "valor", f"{alvo}={valor}", simples=valor):
                achados.append(fora(ficheiro, check.linha, "valor", f"{alvo}={valor}"))

    # Uma coluna com dominio no dicionario dentro de um CHECK de que nao se tirou
    # valor nenhum para ela: `estado SIMILAR TO '(a|b)'`, `estado ~ '…'`.
    lidas = {(c.tabela, c.coluna, c.linha) for c in checks}
    for tabela, identificadores, linha in objectos.checks_brutos:
        for coluna in dict.fromkeys(identificadores):
            dominio = dicionario.dominio_de(tabela, coluna)
            if dominio and not any(t == tabela and c == coluna for t, c, _ in lidas):
                achados.append(
                    Achado(
                        ficheiro,
                        linha,
                        ILEGIVEL,
                        f"`{tabela}.{coluna}` tem dominio no dicionário §{dominio['seccao']} "
                        f"(`{', '.join(dominio['valores'])}`) e aparece num CHECK que o gate 3b nao "
                        "consegue ler. Escreva-o como `coluna IN ('a', 'b', …)`",
                    )
                )

    # Uma coluna cujo dominio o dicionario fixa **para aquela tabela**, criada
    # sem CHECK fechado nem ENUM: o dominio fica por impor.
    for tabela, coluna, _, linha in objectos.tipos_de_coluna:
        dominio = dicionario.dominio_qualificado(tabela, coluna)
        if dominio and (tabela, coluna) not in com_dominio_lido:
            achados.append(
                Achado(
                    ficheiro,
                    linha,
                    REGRA,
                    f"`{tabela}.{coluna}` sem CHECK fechado → `{', '.join(dominio['valores'])}`, "
                    f"dicionário §{dominio['seccao']} (o dominio tem de estar imposto por "
                    "`CHECK (coluna IN (…))` ou por um ENUM, nesta revisao)",
                )
            )

    for tabela, colunas, linha in objectos.unicidades:
        for proibida in saber.politica.unicidades_proibidas:
            if sorted(colunas) == sorted(proibida["colunas"]):
                achados.append(
                    Achado(
                        ficheiro,
                        linha,
                        REGRA,
                        f"`UNIQUE({', '.join(colunas)})` em `{tabela}` → "
                        f"`{proibida['canonico']}`, dicionário §{proibida['seccao']}",
                    )
                )

    for forma, linha in objectos.desconhecidas:
        achados.append(
            Achado(
                ficheiro,
                linha,
                ILEGIVEL,
                f"instrucao `{forma}` que o gate 3b nao sabe ler. Nao e saltada: ou a "
                "forma entra em tools/canon_lint/sql.py, ou a instrucao muda",
            )
        )
    return achados, valores_lidos


def verificar_blocos(blocos: list[revisao.Bloco], ficheiro: str, saber: Saber) -> tuple[list[Achado], Contagem]:
    """Verifica o SQL de um ficheiro: nivel 1 bloco a bloco, nivel 2 sobre o conjunto."""
    achados: list[Achado] = []
    todos = sql.Objectos()
    for bloco in blocos:
        sufixo = f" ({bloco.origem})" if bloco.origem else ""
        try:
            objectos, tokens = sql.analisar(bloco.texto)
        except sql.SqlIlegivel as excepcao:
            achados.append(
                Achado(ficheiro, bloco.linha, ILEGIVEL, f"SQL que nao se consegue ler: {excepcao}{sufixo}")
            )
            continue
        # Um bloco que vem de um auxiliar e todo atribuido a linha da chamada.
        desloca = bloco.linha if not bloco.origem else bloco.linha
        if bloco.origem:
            tokens = [sql.Token(t.tipo, t.valor, 1) for t in tokens]
            reposto = sql.Objectos()
            reposto.juntar(objectos)
            for campo in ("esquemas", "papeis", "tipos", "desconhecidas"):
                setattr(reposto, campo, [(n, 1) for n, _ in getattr(reposto, campo)])
            reposto.tabelas = [(e, n, 1) for e, n, _ in reposto.tabelas]
            reposto.colunas = [(t, c, 1) for t, c, _ in reposto.colunas]
            reposto.tipos_de_coluna = [(t, c, i, 1) for t, c, i, _ in reposto.tipos_de_coluna]
            reposto.checks = [sql.Check(c.tabela, c.coluna, c.valores, c.fechado, 1) for c in reposto.checks]
            reposto.checks_brutos = [(t, i, 1) for t, i, _ in reposto.checks_brutos]
            reposto.unicidades = [(t, c, 1) for t, c, _ in reposto.unicidades]
            reposto.enums = {n: (v, 1) for n, (v, _) in reposto.enums.items()}
            objectos = reposto
        _nivel1(tokens, desloca, ficheiro, saber, sufixo, achados)
        todos.juntar(objectos, desloca - 1)

    novos, valores = _nivel2(todos, ficheiro, saber)
    achados += novos
    contagem = Contagem(
        instrucoes=todos.instrucoes,
        tabelas=len(todos.tabelas),
        colunas=len(todos.colunas),
        valores=valores,
        opacos=todos.opacos,
    )
    return achados, contagem


def verificar_sql(texto: str, base: int, ficheiro: str, saber: Saber) -> tuple[list[Achado], Contagem]:
    """Verifica um texto SQL. `base` e a linha do ficheiro onde ele comeca."""
    return verificar_blocos([revisao.Bloco(texto, base)], ficheiro, saber)


def verificar(ficheiro: str, fonte: str, saber: Saber) -> tuple[list[Achado], Contagem]:
    """Verifica uma migracao: `.py` (revisao Alembic) ou `.sql`."""
    if ficheiro.lower().endswith(".sql"):
        return verificar_sql(fonte, 1, ficheiro, saber)

    try:
        extraccao = revisao.extrair(fonte, saber.politica.auxiliares, saber.carregar)
    except SyntaxError as excepcao:
        return (
            [Achado(ficheiro, excepcao.lineno or 0, ILEGIVEL, f"Python invalido: {excepcao.msg}")],
            Contagem(),
        )
    achados = [Achado(ficheiro, linha, ILEGIVEL, mensagem) for linha, mensagem in extraccao.ilegiveis]
    novos, contagem = verificar_blocos(extraccao.blocos, ficheiro, saber)
    return achados + novos, contagem


__all__ = ["Contagem", "verificar", "verificar_blocos", "verificar_sql", "FORA"]
