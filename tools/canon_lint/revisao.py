"""De uma revisao Alembic ao SQL que ela executa — por leitura, sem a correr.

As migracoes deste repositorio sao Python que passa SQL a `op.execute(...)`. O
gate 3b tem de saber **que SQL e esse**. Uma regex sobre o ficheiro apanhava SQL
em comentarios e perdia o que estivesse partido por varias cadeias; importar e
correr a revisao exigia o Alembic instalado e uma base de dados.

Faz-se a terceira coisa: le-se a arvore sintactica (`ast`) e **segue-se** o que
e determinavel sem executar nada. E um avaliador pequeno e fechado:

* cadeias literais, concatenacao, `text("…")`, e constantes de modulo
  atribuidas **uma unica vez** (uma constante reatribuida ou sombreada por uma
  variavel local deixa de ser constante);
* *f-strings* cujas partes se resolvem a texto: nomes ligados, `", ".join(x)`,
  e chamadas a funcoes puras do proprio modulo (`predicado(coluna)`);
* ciclos `for` sobre uma constante (`for tabela, colunas in MAPA.items()`), que
  se desdobram iteracao a iteracao;
* chamadas a funcoes do proprio modulo e a **modulos auxiliares declarados** em
  `ci/canon-lint.yaml` (`rls.enable_tenant_rls("tenants", coluna="id")`): a
  funcao e lida no ficheiro declarado e o seu corpo e seguido com os argumentos
  da chamada, pelo que o SQL que sai e o que a revisao executaria.

**Tudo o resto falha, com a linha.** Um argumento que nao se resolve, a API de
operacoes do Alembic (`op.create_table`), `sa.Table`/`MetaData`, um `import` de
um modulo nao declarado, `exec`/`eval`, o objecto `op` usado de outra forma que
nao `op.<metodo>(…)` (um alias `run = op.execute`, um `getattr(op, …)`), e uma
revisao de que nao se leu instrucao nenhuma. O lint nao tenta adivinhar: o que
nao segue, recusa.

Limite dito: isto segue chamadas **directas**. Indireccao deliberada (um
dicionario de funcoes, um decorador que executa SQL) nao e seguida — e nao
passa em silencio so quando toca num dos nomes acima.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from typing import Callable

#: Chamadas `op.<x>` que nao executam DDL.
OP_INOFENSIVAS = {"execute", "get_bind", "get_context", "inline_literal", "f"}
#: Metodos que executam SQL, em `op` ou numa ligacao.
EXECUTAM = {"execute", "exec_driver_sql", "executescript", "executemany", "scalar", "scalars"}
#: Construtores de SQL que so se aceitam como argumento directo de um dos acima.
ENVOLVEM_SQL = {"text", "DDL"}
#: Metadados do SQLAlchemy: criam tabelas sem SQL nenhum a vista.
METADADOS = {"Table", "MetaData", "Column"}
#: Funcoes que executam codigo que nao se le.
OPACAS = {"exec", "eval", "compile", "__import__"}

#: Chave do ambiente onde vai a contagem de ligacoes da funcao em curso. Nao e
#: um identificador valido, pelo que nenhum nome do programa colide com ela.
_ESCOPO = "<escopo>"

_LIMITE_DE_ITERACOES = 500
_LIMITE_DE_PROFUNDIDADE = 8


class NaoLiteral(Exception):
    """A expressao nao se resolve a um valor sem executar o programa."""


@dataclass
class Bloco:
    texto: str
    linha: int  # linha do ficheiro da revisao a que o SQL se atribui
    origem: str = ""  # "via rls.enable_tenant_rls", quando vem de um auxiliar


@dataclass
class Extraccao:
    blocos: list[Bloco] = field(default_factory=list)
    ilegiveis: list[tuple[int, str]] = field(default_factory=list)

    def ilegivel(self, linha: int, mensagem: str) -> None:
        if (linha, mensagem) not in self.ilegiveis:
            self.ilegiveis.append((linha, mensagem))


class Modulo:
    """Um ficheiro Python lido: imports, constantes e funcoes de topo."""

    def __init__(self, fonte: str, auxiliares: dict[str, str]) -> None:
        self.arvore = ast.parse(fonte)
        self.pais: dict[int, ast.AST] = {}
        for no in ast.walk(self.arvore):
            for filho in ast.iter_child_nodes(no):
                self.pais[id(filho)] = no

        self.op: set[str] = set()  # nomes ligados ao objecto `alembic.op`
        self.op_funcoes: dict[str, str] = {}  # `from alembic.op import execute as e`
        self.alembic: set[str] = set()  # nomes ligados ao modulo `alembic`
        self.sa: set[str] = set()  # nomes ligados ao modulo `sqlalchemy`
        self.sa_directos: dict[str, str] = {}  # `from sqlalchemy import text as t`
        self.auxiliares: dict[str, str] = {}  # alias -> modulo auxiliar declarado
        self.auxiliares_directos: dict[str, tuple[str, str]] = {}  # nome -> (modulo, funcao)
        self.imports_desconhecidos: list[tuple[int, str]] = []
        self._ler_imports(auxiliares)

        self.funcoes: dict[str, ast.FunctionDef] = {
            no.name: no for no in self.arvore.body if isinstance(no, ast.FunctionDef)
        }

        # Quantas vezes cada nome e ligado, em TODO o modulo: atribuicoes,
        # parametros, alvos de `for`/`with`, `global`, imports. Uma constante
        # ou uma variavel local so se resolve se o seu nome for ligado uma vez.
        self.ligacoes = self._contar([self.arvore])
        #: Os nomes ligados no topo do modulo (fora de funcoes e classes). Uma
        #: variavel local com um destes nomes e uma sombra, e nao se resolve.
        self.topo = set(
            self._contar(
                [n for n in self.arvore.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef))]
            )
        ) | {n.name for n in self.arvore.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        self._escopos: dict[int, dict[str, int]] = {}

        self.constantes: dict[str, object] = {}
        for no in self.arvore.body:
            alvo = None
            if isinstance(no, ast.Assign) and len(no.targets) == 1 and isinstance(no.targets[0], ast.Name):
                alvo, valor = no.targets[0].id, no.value
            elif isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name) and no.value is not None:
                alvo, valor = no.target.id, no.value
            if alvo is None or self.ligacoes.get(alvo, 0) != 1:
                continue
            try:
                self.constantes[alvo] = ast.literal_eval(valor)
            except (ValueError, SyntaxError):
                continue

    @staticmethod
    def _contar(raizes: list[ast.AST]) -> dict[str, int]:
        """Quantas vezes cada nome e ligado debaixo de `raizes`."""
        contagem: dict[str, int] = {}
        for raiz in raizes:
            for no in ast.walk(raiz):
                nomes: list[str] = []
                if isinstance(no, ast.Name) and isinstance(no.ctx, (ast.Store, ast.Del)):
                    nomes.append(no.id)
                elif isinstance(no, ast.arg):
                    nomes.append(no.arg)
                elif isinstance(no, (ast.Global, ast.Nonlocal)):
                    nomes += no.names
                elif isinstance(no, (ast.Import, ast.ImportFrom)):
                    nomes += [(a.asname or a.name).split(".")[0] for a in no.names]
                elif isinstance(no, (ast.FunctionDef, ast.ClassDef)) and no is not raiz:
                    nomes.append(no.name)
                for nome in nomes:
                    contagem[nome] = contagem.get(nome, 0) + 1
        return contagem

    def escopo(self, funcao: ast.FunctionDef) -> dict[str, int]:
        """As ligacoes dentro de uma funcao: e o que decide se uma local se resolve."""
        if id(funcao) not in self._escopos:
            self._escopos[id(funcao)] = self._contar([funcao])
        return self._escopos[id(funcao)]

    def _ler_imports(self, auxiliares: dict[str, str]) -> None:
        for no in ast.walk(self.arvore):
            if isinstance(no, ast.Import):
                for alias in no.names:
                    nome, como = alias.name, alias.asname
                    raiz = nome.split(".")[0]
                    if nome == "alembic.op" and como:
                        self.op.add(como)
                    elif raiz == "alembic":
                        self.alembic.add(como or raiz)
                    elif raiz == "sqlalchemy":
                        self.sa.add(como or raiz)
                    elif nome in auxiliares:
                        self.auxiliares[como or nome] = nome
                    elif raiz not in sys.stdlib_module_names:
                        self.imports_desconhecidos.append((no.lineno, nome))
            elif isinstance(no, ast.ImportFrom):
                modulo = no.module or ""
                raiz = modulo.split(".")[0]
                for alias in no.names:
                    como = alias.asname or alias.name
                    if modulo == "alembic" and alias.name == "op":
                        self.op.add(como)
                    elif modulo == "alembic.op":
                        self.op_funcoes[como] = alias.name
                    elif raiz == "alembic":
                        pass
                    elif raiz == "sqlalchemy":
                        self.sa_directos[como] = alias.name
                    elif modulo in auxiliares:
                        self.auxiliares_directos[como] = (modulo, alias.name)
                    elif no.level or raiz not in sys.stdlib_module_names:
                        self.imports_desconhecidos.append((no.lineno, modulo or "." * no.level))

    # ------------------------------------------------------------ classificacao

    def e_op(self, no: ast.AST) -> bool:
        """`no` e o objecto `alembic.op` (por qualquer dos nomes que tenha)?"""
        if isinstance(no, ast.Name):
            return no.id in self.op
        return (
            isinstance(no, ast.Attribute)
            and no.attr == "op"
            and isinstance(no.value, ast.Name)
            and no.value.id in self.alembic
        )

    def envolve_sql(self, chamada: ast.Call) -> bool:
        funcao = chamada.func
        if isinstance(funcao, ast.Name):
            return self.sa_directos.get(funcao.id) in ENVOLVEM_SQL
        return (
            isinstance(funcao, ast.Attribute)
            and funcao.attr in ENVOLVEM_SQL
            and isinstance(funcao.value, ast.Name)
            and funcao.value.id in self.sa
        )

    def classificar(self, chamada: ast.Call) -> tuple[str, str]:
        """(classe, pormenor): sql | api | auxiliar | local | envolve | metadados | opaca | outra."""
        funcao = chamada.func
        if isinstance(funcao, ast.Attribute):
            dono, metodo = funcao.value, funcao.attr
            if self.e_op(dono):
                if metodo == "execute":
                    return "sql", "op.execute"
                return ("outra", "") if metodo in OP_INOFENSIVAS else ("api", metodo)
            if isinstance(dono, ast.Name) and dono.id in self.auxiliares:
                return "auxiliar", f"{self.auxiliares[dono.id]}.{metodo}"
            if isinstance(dono, ast.Name) and dono.id in self.sa and metodo in METADADOS:
                return "metadados", metodo
            if self.envolve_sql(chamada):
                return "envolve", metodo
            if metodo in EXECUTAM:
                return "sql", metodo
            return "outra", ""
        if isinstance(funcao, ast.Name):
            nome = funcao.id
            if nome in self.op_funcoes:
                metodo = self.op_funcoes[nome]
                if metodo == "execute":
                    return "sql", "op.execute"
                return ("outra", "") if metodo in OP_INOFENSIVAS else ("api", metodo)
            if nome in self.auxiliares_directos:
                modulo, funcao_aux = self.auxiliares_directos[nome]
                return "auxiliar", f"{modulo}.{funcao_aux}"
            if self.sa_directos.get(nome) in METADADOS:
                return "metadados", self.sa_directos[nome]
            if self.envolve_sql(chamada):
                return "envolve", nome
            if nome in OPACAS:
                return "opaca", nome
            if nome in self.funcoes:
                return "local", nome
        return "outra", ""

    def chega_a_sql(self, funcao: ast.FunctionDef, vistos: frozenset[str] = frozenset()) -> bool:
        """A funcao (ou o que ela chama no proprio modulo) executa SQL?"""
        for no in ast.walk(funcao):
            if not isinstance(no, ast.Call):
                continue
            classe, pormenor = self.classificar(no)
            if classe in ("sql", "api", "auxiliar", "metadados", "opaca", "envolve"):
                return True
            if classe == "local" and pormenor not in vistos and pormenor != funcao.name:
                if self.chega_a_sql(self.funcoes[pormenor], vistos | {funcao.name}):
                    return True
        return False


class Leitor:
    """Segue uma revisao e devolve os blocos de SQL que ela executa."""

    def __init__(self, auxiliares: dict[str, str], carregar: Callable[[str], str | None]) -> None:
        self.auxiliares = auxiliares  # nome do modulo -> caminho relativo
        self.carregar = carregar
        self._modulos: dict[str, Modulo | None] = {}
        self.resultado = Extraccao()

    # ------------------------------------------------------------- entrada

    def ler(self, fonte: str) -> Extraccao:
        modulo = Modulo(fonte, self.auxiliares)
        resultado = self.resultado

        for linha, nome in modulo.imports_desconhecidos:
            resultado.ilegivel(
                linha,
                f"`import {nome}`: modulo que o gate 3b nao conhece. Se executa SQL, declare-o em "
                "ci/canon-lint.yaml (`auxiliares_de_migracao`); o lint so segue o que esta declarado",
            )
        self._usos_indevidos(modulo)

        # O que o Alembic corre: o topo do modulo, `upgrade` e `downgrade`.
        topo = [n for n in modulo.arvore.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        self._executar(topo, {}, modulo, None, 0)
        corpos = []
        for nome in ("upgrade", "downgrade"):
            if nome in modulo.funcoes:
                corpo = modulo.funcoes[nome].body
                corpos.append(corpo)
                self._executar(corpo, {_ESCOPO: modulo.escopo(modulo.funcoes[nome])}, modulo, None, 0)

        if not resultado.blocos and not resultado.ilegiveis and not self._vazia(corpos):
            resultado.ilegivel(
                1,
                "revisao de que nao se leu nenhuma instrucao SQL: ou o DDL esta escrito de uma "
                "forma que o gate 3b nao segue, ou o ficheiro nao e uma revisao",
            )
        return resultado

    @staticmethod
    def _vazia(corpos: list[list[ast.stmt]]) -> bool:
        """`True` se `upgrade`/`downgrade` so tem `pass` e docstring (revisao de *merge*)."""
        if not corpos:
            return False
        for corpo in corpos:
            for no in corpo:
                if isinstance(no, ast.Pass):
                    continue
                if isinstance(no, ast.Expr) and isinstance(no.value, ast.Constant):
                    continue
                return False
        return True

    def _usos_indevidos(self, modulo: Modulo) -> None:
        """O objecto `op` so pode aparecer como `op.<metodo>(…)`; metadados nunca."""
        for no in ast.walk(modulo.arvore):
            if isinstance(no, ast.Name) and isinstance(no.ctx, ast.Load):
                pai = modulo.pais.get(id(no))
                if no.id in modulo.op:
                    avo = modulo.pais.get(id(pai)) if pai is not None else None
                    directo = (
                        isinstance(pai, ast.Attribute)
                        and isinstance(avo, ast.Call)
                        and avo.func is pai
                    )
                    if not directo:
                        self.resultado.ilegivel(
                            no.lineno,
                            f"`{no.id}` (alembic.op) usado fora de uma chamada directa "
                            f"`{no.id}.<metodo>(…)`: um alias ou um `getattr` esconde o SQL do gate 3b",
                        )
                elif no.id in modulo.op_funcoes:
                    if not (isinstance(pai, ast.Call) and pai.func is no):
                        self.resultado.ilegivel(
                            no.lineno, f"`{no.id}` (alembic.op) usado fora de uma chamada directa"
                        )
                elif modulo.sa_directos.get(no.id) in METADADOS:
                    self.resultado.ilegivel(
                        no.lineno,
                        f"`{modulo.sa_directos[no.id]}` do SQLAlchemy: tabelas definidas por metadados "
                        "nao sao lidas pelo gate 3b. Use `op.execute` com SQL literal",
                    )
            elif (
                isinstance(no, ast.Attribute)
                and no.attr in METADADOS
                and isinstance(no.value, ast.Name)
                and no.value.id in modulo.sa
            ):
                self.resultado.ilegivel(
                    no.lineno,
                    f"`{no.value.id}.{no.attr}`: tabelas definidas por metadados do SQLAlchemy nao "
                    "sao lidas pelo gate 3b. Use `op.execute` com SQL literal",
                )

    # ------------------------------------------------------------- instrucoes

    def _executar(self, corpo, ambiente: dict, modulo: Modulo, origem, profundidade: int) -> None:
        for no in corpo:
            if isinstance(no, (ast.Import, ast.ImportFrom, ast.Pass, ast.Global, ast.Nonlocal)):
                continue
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if any(
                    isinstance(n, ast.Call) and modulo.classificar(n)[0] != "outra" for n in ast.walk(no)
                ):
                    self.resultado.ilegivel(
                        self._linha(no, origem),
                        f"`{no.name}` definido dentro de uma funcao e a executar SQL: o gate 3b nao o segue",
                    )
                continue
            if isinstance(no, ast.For):
                self._para(no, ambiente, modulo, origem, profundidade)
                continue
            if isinstance(no, (ast.If, ast.While)):
                self._expressao(no.test, ambiente, modulo, origem, profundidade)
                self._executar(no.body, ambiente, modulo, origem, profundidade)
                self._executar(no.orelse, ambiente, modulo, origem, profundidade)
                continue
            if isinstance(no, (ast.With, ast.AsyncWith)):
                for item in no.items:
                    self._expressao(item.context_expr, ambiente, modulo, origem, profundidade)
                self._executar(no.body, ambiente, modulo, origem, profundidade)
                continue
            if isinstance(no, ast.Try):
                for parte in (no.body, no.orelse, no.finalbody):
                    self._executar(parte, ambiente, modulo, origem, profundidade)
                for tratador in no.handlers:
                    self._executar(tratador.body, ambiente, modulo, origem, profundidade)
                continue
            if isinstance(no, ast.Assign):
                self._expressao(no.value, ambiente, modulo, origem, profundidade)
                # Uma variavel local so se resolve se o nome for ligado uma unica
                # vez no modulo inteiro: nem reatribuida, nem sombra de outra.
                if len(no.targets) == 1 and isinstance(no.targets[0], ast.Name):
                    nome = no.targets[0].id
                    escopo = ambiente.get(_ESCOPO)
                    if escopo is not None and escopo.get(nome, 0) == 1 and nome not in modulo.topo:
                        try:
                            ambiente[nome] = self._avaliar(no.value, ambiente, modulo, profundidade)
                        except NaoLiteral:
                            ambiente.pop(nome, None)
                continue
            for filho in ast.iter_child_nodes(no):
                if isinstance(filho, ast.expr):
                    self._expressao(filho, ambiente, modulo, origem, profundidade)

    def _para(self, no: ast.For, ambiente: dict, modulo: Modulo, origem, profundidade: int) -> None:
        alvos = self._alvos(no.target)
        try:
            sequencia = self._sequencia(no.iter, ambiente, modulo, profundidade)
        except NaoLiteral:
            sequencia = None
        if sequencia is None or alvos is None or len(sequencia) > _LIMITE_DE_ITERACOES:
            # Nao se desdobra: segue-se o corpo com os alvos por ligar. Se eles
            # chegarem a um `execute`, a chamada falha como nao literal.
            self._expressao(no.iter, ambiente, modulo, origem, profundidade)
            livre = {k: v for k, v in ambiente.items() if alvos is None or k not in alvos}
            self._executar(no.body, livre, modulo, origem, profundidade)
            self._executar(no.orelse, livre, modulo, origem, profundidade)
            return
        for item in sequencia:
            local = dict(ambiente)
            if len(alvos) == 1:
                local[alvos[0]] = item
            elif isinstance(item, (tuple, list)) and len(item) == len(alvos):
                local.update(zip(alvos, item))
            else:
                local = {k: v for k, v in ambiente.items() if k not in alvos}
            self._executar(no.body, local, modulo, origem, profundidade)
        self._executar(no.orelse, ambiente, modulo, origem, profundidade)

    @staticmethod
    def _alvos(alvo: ast.expr) -> list[str] | None:
        if isinstance(alvo, ast.Name):
            return [alvo.id]
        if isinstance(alvo, (ast.Tuple, ast.List)) and all(isinstance(e, ast.Name) for e in alvo.elts):
            return [e.id for e in alvo.elts]
        return None

    def _sequencia(self, no: ast.expr, ambiente: dict, modulo: Modulo, profundidade: int) -> list:
        if (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr in ("items", "keys", "values")
            and not no.args
            and not no.keywords
        ):
            mapa = self._avaliar(no.func.value, ambiente, modulo, profundidade)
            if not isinstance(mapa, dict):
                raise NaoLiteral("nao e um mapa")
            return list(getattr(mapa, no.func.attr)())
        valor = self._avaliar(no, ambiente, modulo, profundidade)
        if isinstance(valor, dict):
            return list(valor)
        if isinstance(valor, (tuple, list)):
            return list(valor)
        raise NaoLiteral("nao e uma sequencia")

    # ------------------------------------------------------------- expressoes

    def _linha(self, no: ast.AST, origem) -> int:
        return origem[0] if origem else getattr(no, "lineno", 0)

    def _expressao(self, expressao, ambiente: dict, modulo: Modulo, origem, profundidade: int) -> None:
        """Procura, dentro de uma expressao, as chamadas que executam SQL."""
        if expressao is None:
            return
        consumidos: set[int] = set()
        for no in ast.walk(expressao):
            if not isinstance(no, ast.Call) or id(no) in consumidos:
                continue
            classe, pormenor = modulo.classificar(no)
            linha = self._linha(no, origem)
            sufixo = f" ({origem[1]})" if origem else ""
            if classe == "sql":
                argumento = no.args[0] if no.args else next(
                    (k.value for k in no.keywords if k.arg in ("sqltext", "statement", "sql")), None
                )
                if argumento is None:
                    self.resultado.ilegivel(linha, f"`{pormenor}()` sem SQL{sufixo}")
                    continue
                for interior in ast.walk(argumento):
                    consumidos.add(id(interior))
                try:
                    valor = self._avaliar(argumento, ambiente, modulo, profundidade)
                    if not isinstance(valor, str):
                        raise NaoLiteral("o argumento nao e texto")
                except NaoLiteral as excepcao:
                    self.resultado.ilegivel(
                        linha,
                        f"`{pormenor}(...)` com SQL que o gate 3b nao consegue resolver sem executar "
                        f"a revisao ({excepcao}){sufixo}. Escreva a instrucao por extenso, ou com "
                        "*f-strings* sobre constantes de modulo",
                    )
                    continue
                self.resultado.blocos.append(
                    Bloco(valor, linha if origem else argumento.lineno, origem[1] if origem else "")
                )
            elif classe == "api":
                self.resultado.ilegivel(
                    linha,
                    f"`op.{pormenor}(...)`: a API de operacoes do Alembic nao e lida pelo gate 3b"
                    f"{sufixo}. Use `op.execute` com SQL literal, como a revisao 0001",
                )
            elif classe == "metadados":
                pass  # reportado por `_usos_indevidos`, uma vez
            elif classe == "opaca":
                self.resultado.ilegivel(linha, f"`{pormenor}(...)` executa codigo que o gate 3b nao le{sufixo}")
            elif classe == "envolve":
                self.resultado.ilegivel(
                    linha,
                    f"`{pormenor}(...)` constroi SQL que nao vai directamente para um `execute` lido"
                    f"{sufixo}: o gate 3b nao sabe onde ele acaba",
                )
            elif classe == "auxiliar":
                self._auxiliar(no, pormenor, ambiente, modulo, origem, profundidade)
            elif classe == "local":
                funcao = modulo.funcoes[pormenor]
                if modulo.chega_a_sql(funcao):
                    self._chamar(no, funcao, modulo, pormenor, ambiente, modulo, origem, profundidade)

    def _auxiliar(self, chamada, alvo: str, ambiente, modulo, origem, profundidade) -> None:
        nome_modulo, _, nome_funcao = alvo.rpartition(".")
        linha = self._linha(chamada, origem)
        auxiliar = self._modulo_auxiliar(nome_modulo)
        if auxiliar is None:
            self.resultado.ilegivel(
                linha,
                f"`{alvo}(...)`: o modulo auxiliar `{nome_modulo}` esta declarado em "
                f"ci/canon-lint.yaml e o ficheiro `{self.auxiliares.get(nome_modulo)}` nao se le",
            )
            return
        funcao = auxiliar.funcoes.get(nome_funcao)
        if funcao is None:
            self.resultado.ilegivel(linha, f"`{alvo}(...)`: a funcao nao existe no modulo auxiliar")
            return
        self._chamar(chamada, funcao, auxiliar, alvo, ambiente, modulo, origem, profundidade)

    def _modulo_auxiliar(self, nome: str) -> Modulo | None:
        if nome not in self._modulos:
            fonte = self.carregar(self.auxiliares[nome])
            try:
                self._modulos[nome] = Modulo(fonte, self.auxiliares) if fonte is not None else None
            except SyntaxError:
                self._modulos[nome] = None
        return self._modulos[nome]

    def _ligar(self, chamada: ast.Call, funcao: ast.FunctionDef, ambiente, modulo_chamador, modulo_funcao, profundidade) -> dict:
        """Os parametros de `funcao` com os valores da chamada. `NaoLiteral` se nao der."""
        argumentos = funcao.args
        if argumentos.vararg or argumentos.kwarg or argumentos.posonlyargs or argumentos.kwonlyargs:
            raise NaoLiteral("a funcao tem *args, **kwargs ou parametros so por nome")
        nomes = [a.arg for a in argumentos.args]
        local: dict = {_ESCOPO: modulo_funcao.escopo(funcao)}
        if len(chamada.args) > len(nomes) or any(isinstance(a, ast.Starred) for a in chamada.args):
            raise NaoLiteral("argumentos a mais ou desempacotados")
        for nome, argumento in zip(nomes, chamada.args):
            local[nome] = self._avaliar(argumento, ambiente, modulo_chamador, profundidade)
        for chave in chamada.keywords:
            if chave.arg is None or chave.arg not in nomes or chave.arg in local:
                raise NaoLiteral("argumento por nome que a funcao nao tem")
            local[chave.arg] = self._avaliar(chave.value, ambiente, modulo_chamador, profundidade)
        omissoes = argumentos.defaults
        for nome, omissao in zip(nomes[len(nomes) - len(omissoes):], omissoes):
            if nome not in local:
                local[nome] = self._avaliar(omissao, {}, modulo_funcao, profundidade)
        em_falta = [n for n in nomes if n not in local]
        if em_falta:
            raise NaoLiteral(f"falta o argumento `{em_falta[0]}`")
        return local

    def _chamar(self, chamada, funcao, modulo_funcao, rotulo, ambiente, modulo_chamador, origem, profundidade) -> None:
        linha = self._linha(chamada, origem)
        if profundidade >= _LIMITE_DE_PROFUNDIDADE:
            self.resultado.ilegivel(linha, f"`{rotulo}(...)`: chamadas encadeadas a mais para o gate 3b seguir")
            return
        try:
            local = self._ligar(chamada, funcao, ambiente, modulo_chamador, modulo_funcao, profundidade)
        except NaoLiteral as excepcao:
            self.resultado.ilegivel(
                linha,
                f"`{rotulo}(...)` executa SQL e os seus argumentos nao se resolvem sem correr a "
                f"revisao ({excepcao}). Passe literais ou constantes de modulo",
            )
            return
        nova_origem = origem or (chamada.lineno, f"via {rotulo}")
        self._executar(funcao.body, local, modulo_funcao, nova_origem, profundidade + 1)

    def _avaliar(self, no: ast.expr, ambiente: dict, modulo: Modulo, profundidade: int):
        """O valor de uma expressao, se for determinavel sem executar nada."""
        if isinstance(no, ast.Constant):
            if isinstance(no.value, (str, int)) and not isinstance(no.value, bool):
                return no.value
            raise NaoLiteral(f"constante de tipo {type(no.value).__name__}")
        if isinstance(no, ast.Name):
            if no.id in ambiente:
                return ambiente[no.id]
            if no.id in modulo.constantes:
                return modulo.constantes[no.id]
            if modulo.ligacoes.get(no.id, 0) > 1:
                raise NaoLiteral(f"`{no.id}` e atribuido mais de uma vez, ou sombreado")
            raise NaoLiteral(f"`{no.id}` nao e uma constante de modulo")
        if isinstance(no, ast.JoinedStr):
            partes: list[str] = []
            for parte in no.values:
                if isinstance(parte, ast.Constant):
                    partes.append(str(parte.value))
                elif isinstance(parte, ast.FormattedValue):
                    if parte.conversion != -1 or parte.format_spec is not None:
                        raise NaoLiteral("f-string com conversao ou formato")
                    valor = self._avaliar(parte.value, ambiente, modulo, profundidade)
                    if not isinstance(valor, (str, int)):
                        raise NaoLiteral("f-string com um valor que nao e texto")
                    partes.append(str(valor))
                else:
                    raise NaoLiteral("f-string de forma desconhecida")
            return "".join(partes)
        if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Add):
            esquerda = self._avaliar(no.left, ambiente, modulo, profundidade)
            direita = self._avaliar(no.right, ambiente, modulo, profundidade)
            if isinstance(esquerda, str) and isinstance(direita, str):
                return esquerda + direita
            raise NaoLiteral("soma que nao e de textos")
        if isinstance(no, (ast.Tuple, ast.List)):
            return [self._avaliar(e, ambiente, modulo, profundidade) for e in no.elts]
        if isinstance(no, ast.Dict):
            if any(k is None for k in no.keys):
                raise NaoLiteral("mapa com desempacotamento")
            return {
                self._avaliar(k, ambiente, modulo, profundidade): self._avaliar(v, ambiente, modulo, profundidade)
                for k, v in zip(no.keys, no.values)
            }
        if isinstance(no, ast.Call):
            if modulo.envolve_sql(no) and len(no.args) == 1 and not no.keywords:
                return self._avaliar(no.args[0], ambiente, modulo, profundidade)
            funcao = no.func
            # "sep".join(sequencia)
            if (
                isinstance(funcao, ast.Attribute)
                and funcao.attr == "join"
                and len(no.args) == 1
                and not no.keywords
            ):
                separador = self._avaliar(funcao.value, ambiente, modulo, profundidade)
                itens = self._avaliar(no.args[0], ambiente, modulo, profundidade)
                if isinstance(separador, str) and isinstance(itens, (list, tuple)) and all(
                    isinstance(i, str) for i in itens
                ):
                    return separador.join(itens)
                raise NaoLiteral("`join` sobre algo que nao e uma lista de textos")
            # funcao pura do proprio modulo: `predicado(coluna)`
            if isinstance(funcao, ast.Name) and funcao.id in modulo.funcoes:
                return self._funcao_pura(no, modulo.funcoes[funcao.id], ambiente, modulo, profundidade)
            raise NaoLiteral("chamada a uma funcao que o gate 3b nao segue")
        raise NaoLiteral(f"expressao {type(no).__name__}")

    def _funcao_pura(self, chamada, funcao: ast.FunctionDef, ambiente, modulo: Modulo, profundidade: int):
        if profundidade >= _LIMITE_DE_PROFUNDIDADE:
            raise NaoLiteral("chamadas encadeadas a mais")
        if modulo.chega_a_sql(funcao):
            raise NaoLiteral(f"`{funcao.name}` executa SQL; nao e uma funcao pura")
        local = self._ligar(chamada, funcao, ambiente, modulo, modulo, profundidade)
        retorno = None
        for no in funcao.body:
            if isinstance(no, ast.Expr):
                continue  # docstring, ou uma validacao que nao devolve nada
            if isinstance(no, ast.Return) and retorno is None and no.value is not None:
                retorno = no.value
                continue
            raise NaoLiteral(f"`{funcao.name}` tem mais do que validacoes e um `return`")
        if retorno is None:
            raise NaoLiteral(f"`{funcao.name}` nao devolve nada")
        return self._avaliar(retorno, local, modulo, profundidade + 1)


def extrair(
    fonte: str,
    auxiliares: dict[str, str] | None = None,
    carregar: Callable[[str], str | None] | None = None,
) -> Extraccao:
    """Os blocos de SQL de uma revisao, e o que nao se conseguiu ler."""
    return Leitor(auxiliares or {}, carregar or (lambda _: None)).ler(fonte)
