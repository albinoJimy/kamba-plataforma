"""Prova por mutacao do *logger* e das suas verificacoes (KAM-068).

    python tools/log_policy/tests/mutacoes.py [filtro] [--docker IMAGEM]
    python tools/log_policy/tests/mutacoes.py --aplicaveis

Um teste que passa nao prova que morde. Isto prova: copia o codigo para um
directorio temporario **fora do repositorio**, confirma que a linha de base
esta verde, e depois aplica **uma** alteracao deliberadamente errada de cada
vez — retirar um padrao, deixar passar um campo desconhecido, deixar de
validar um campo — e exige que os testes fiquem vermelhos. O repositorio nao e
tocado.

Tres corredores, conforme o que a mutacao altera:

  py    as baterias em Python (`libs/py-core/tests/test_logger*.py` e
        `tools/log_policy/tests/`), com o Python que corre este ficheiro;
  ts    `node --test tests/logger.test.ts`, em `packages/core-ts`;
  tsc   a compilacao: uma mutacao aos **tipos** tem de deixar uma directiva
        `@ts-expect-error` por usar. Precisa do `node_modules` do repositorio.

`ts` e `tsc` usam o `node` da maquina, ou um contentor (`--docker
node:24.21.0-trixie-slim`). Sem um nem outro, essas mutacoes ficam **por
correr**, e o relatorio di-lo — nao contam como apanhadas.

`--aplicaveis` confirma, em segundos e sem correr teste nenhum, que o texto de
todas as mutacoes existe exactamente uma vez no ficheiro alvo. Uma mutacao que
deixou de se aplicar e uma prova que deixou de provar.

Nao faz parte de nenhum gate (sao minutos). Corre-se quando se mexe no
*logger*, na politica ou nos testes, e o resultado regista-se na analise do
ticket. Uma mutacao que **sobreviva** e um teste em falta.

Vive em `tests/` e nao se chama `test_*.py`: nao e descoberto pelo `unittest`
nem medido pela cobertura.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]

POL_PY = "libs/py-core/src/kamba_core/logger/politica.py"
LOG_PY = "libs/py-core/src/kamba_core/logger/__init__.py"
PONTE = "libs/py-core/src/kamba_core/logger/ponte.py"
POL_TS = "packages/core-ts/src/logger/politica.ts"
LOG_TS = "packages/core-ts/src/logger/index.ts"
X11 = "tools/log_policy/x11.py"
LINT = "tools/log_policy/lint.py"
CLI = "tools/log_policy/cli.py"
GERADOR = "tools/log_policy/fixtures.py"
AMOSTRA = "tools/log_policy/amostra.py"

#: (nome, corredor, ficheiro, texto antigo, texto novo)
MUTACOES: list[tuple[str, str, str, str, str]] = [
    # ---------------------------------------------------------------- politica (Python)
    ('py: sem a regra dos sete digitos', 'py', POL_PY, '    if len(_DIGITO.findall(texto)) > DIGITOS_MAXIMOS:\n        return False\n', ''),
    ('py: digitos so contam se forem seguidos', 'py', POL_PY, '    if len(_DIGITO.findall(texto)) > DIGITOS_MAXIMOS:', '    if re.search(r"[0-9](?:[^A-Za-z0-9]?[0-9]){6}", texto):'),
    ('py: oito digitos em vez de sete', 'py', POL_PY, 'DIGITOS_MAXIMOS = 6', 'DIGITOS_MAXIMOS = 7'),
    ('py: sem as formas de segredo', 'py', POL_PY, '    return not _FORMA_DE_SEGREDO.search(texto)', '    return True'),
    ("py: identificador com `match` em vez de `fullmatch`", "py", POL_PY,
     "    if not forma.fullmatch(valor) or not _sem_conteudo(valor):\n        return None\n    return valor",
     "    if not forma.match(valor) or not _sem_conteudo(valor):\n        return None\n    return valor"),
    ("py: identificador sem forma (qualquer texto curto)", "py", POL_PY,
     "    if not forma.fullmatch(valor) or not _sem_conteudo(valor):\n        return None\n    return valor",
     "    if not _sem_conteudo(valor):\n        return None\n    return valor"),
    ("py: identificador sem limite de comprimento", "py", POL_PY,
     "    if not 1 <= len(valor) <= COMPRIMENTO_MAXIMO[nome]:\n        return None\n    if not forma",
     "    if not forma"),
    ("py: identificador com digitos em qualquer sitio", "py", POL_PY,
     '_PALAVRA = r"[a-z]+[0-9]{0,3}"', '_PALAVRA = r"[a-z][a-z0-9]*"'),
    ("py: tenant_id aceita qualquer texto", "py", POL_PY,
     "    return minusculas if _UUID.fullmatch(minusculas) else None",
     "    return minusculas"),
    ("py: UUID com `match` (lixo no fim)", "py", POL_PY,
     "    return minusculas if _UUID.fullmatch(minusculas) else None",
     "    return minusculas if _UUID.match(minusculas) else None"),
    ('py: msg_id e turn_id aceitam um wamid em claro', 'py', POL_PY, '    if type(valor) is str and _ID_OPACO.fullmatch(valor):\n        return valor\n    return None', '    if type(valor) is str:\n        return valor\n    return None'),
    ('py: contact_hmac_prefix sem forma', 'py', POL_PY, '        if type(valor) is str and _HMAC_PREFIXO.fullmatch(valor):', '        if type(valor) is str:'),
    ("py: latency_ms sem tecto", "py", POL_PY,
     "            if 0 <= valor <= LATENCIA_MAXIMA_MS:", "            if 0 <= valor:"),
    ('py: latency_ms aceita booleanos e subclasses', 'py', POL_PY, '        if type(valor) is int:', '        if isinstance(valor, int):'),
    ('py: latency_ms aceita texto', 'py', POL_PY, '        if type(valor) is int:\n            if 0 <= valor <= LATENCIA_MAXIMA_MS:\n                return valor\n        return None', '        return valor'),
    ('py: os identificadores aceitam subclasses de str', 'py', POL_PY, 'def _identificador(nome: str, valor: object, forma: re.Pattern[str]) -> str | None:\n    if not type(valor) is str:', 'def _identificador(nome: str, valor: object, forma: re.Pattern[str]) -> str | None:\n    if not isinstance(valor, str):'),
    ('py: error_code aceita subclasses de str', 'py', POL_PY, '    """`<codigo>` ou `<codigo>:<Classe>`, cada parte com a sua forma."""\n    if not type(valor) is str:', '    """`<codigo>` ou `<codigo>:<Classe>`, cada parte com a sua forma."""\n    if not isinstance(valor, str):'),
    ('py: id_opaco levanta com um substituto isolado', 'py', POL_PY, '    limpo = _SUBSTITUTO.sub("\\ufffd", identificador)', '    limpo = identificador'),
    ("py: error_code sem forma no codigo", "py", POL_PY,
     "    if not _CODIGO.fullmatch(codigo) or not _sem_conteudo(codigo):\n        return None",
     "    if not _sem_conteudo(codigo):\n        return None"),
    ("py: error_code sem validar a classe", "py", POL_PY,
     "    if separador and not _classe_valida(classe):\n        return None\n", ""),
    ("py: classe sem limite de grupos de digitos", "py", POL_PY,
     "    return len(grupos) <= 2 and all(len(g) <= 4 for g in grupos)", "    return True"),
    ("py: classe sem a regra dos digitos", "py", POL_PY,
     "    if not _CLASSE.fullmatch(classe) or not _sem_conteudo(classe):",
     "    if not _CLASSE.fullmatch(classe):"),
    ("py: nome_legivel devolve qualquer nome", "py", POL_PY,
     "        and len(nome) <= NOME_LEGIVEL_MAXIMO\n        and _NOME_LEGIVEL.fullmatch(nome)\n",
     ""),
    ("py: id_opaco devolve a entrada", "py", POL_PY,
     '    return f"m_{resumo[:32]}"', "    return identificador"),
    ("py: a mascara mostra quatro caracteres", "py", POL_PY,
     "REFERENCIA_VISIVEIS = 3", "REFERENCIA_VISIVEIS = 4"),
    ("py: a mascara nao tem minimo", "py", POL_PY,
     "REFERENCIA_MINIMO = 8", "REFERENCIA_MINIMO = 0"),
    ("py: a allowlist ganha um campo", "py", POL_PY,
     '    "error_code",\n)\n\n#: Campos que o *logger* preenche.',
     '    "error_code",\n    "mensagem",\n)\n\n#: Campos que o *logger* preenche.'),
    # ---------------------------------------------------------------- logger (Python)
    ('py: um campo desconhecido passa em claro', 'py', LOG_PY, '            elif nome not in CAMPOS_DE_CHAMADA:\n                rejeicoes.append((MOTIVO_DESCONHECIDO, nome_legivel(nome)))\n', '            elif nome not in CAMPOS_DE_CHAMADA:\n                self._escrever(json.dumps({str(nome): valor}, default=str))\n'),
    ('py: um campo desconhecido e ignorado sem contar', 'py', LOG_PY, '            elif nome not in CAMPOS_DE_CHAMADA:\n                rejeicoes.append((MOTIVO_DESCONHECIDO, nome_legivel(nome)))\n', '            elif nome not in CAMPOS_DE_CHAMADA:\n                continue\n'),
    ('py: os campos reservados podem ser dados', 'py', LOG_PY, '            elif nome in CAMPOS_RESERVADOS:\n                rejeicoes.append((MOTIVO_RESERVADO, nome))\n', ''),
    ('py: o valor de um campo reservado vai na mensagem estrita', 'py', LOG_PY, '                rejeicoes.append((MOTIVO_RESERVADO, nome))', '                rejeicoes.append((MOTIVO_RESERVADO, str(valor)))'),
    ('py: o nivel aceita subclasses de str', 'py', LOG_PY, '        if type(nivel) is not str or nivel not in NIVEIS:', '        if not isinstance(nivel, str) or nivel not in NIVEIS:'),
    ('py: os campos aceitam subclasses de dict', 'py', LOG_PY, '        elif type(campos) is not dict:', '        elif not isinstance(campos, dict):'),
    ('py: o nome de um campo aceita subclasses de str', 'py', LOG_PY, '            if type(nome) is not str:\n                rejeicoes.append((MOTIVO_DESCONHECIDO, nome_legivel(nome)))\n            elif', '            if'),
    ('py: sem a rede de registar', 'py', LOG_PY, '        except Exception:\n            CONTADORES.incrementar(METRICA_ESCRITA_FALHADA)\n\n    def _registar', '        except ZeroDivisionError:\n            CONTADORES.incrementar(METRICA_ESCRITA_FALHADA)\n\n    def _registar'),
    ('py: o relogio pode devolver uma subclasse de datetime', 'py', LOG_PY, '    if type(instante) is not datetime.datetime:', '    if not isinstance(instante, datetime.datetime):'),
    ('py: excepcao exige o codigo', 'py', LOG_PY, '    def excepcao(self, erro, codigo=None, /, *posicionais, **campos) -> None:', '    def excepcao(self, erro, codigo, /, *posicionais, **campos) -> None:'),
    ('py: a linha nao e despejada', 'py', LOG_PY, '        destino.flush()\n', ''),
    ('py: a ponte deixa os manipuladores proprios dos outros loggers', 'py', PONTE, '            for existente in list(outro.handlers):\n                outro.removeHandler(existente)\n            outro.propagate = True\n', '            pass\n'),
    ("py: um valor invalido passa em claro", "py", LOG_PY,
     "                if limpo is None:\n                    rejeicoes.append((MOTIVO_VALOR, nome))\n                else:\n                    aceites[nome] = limpo",
     "                aceites[nome] = valor if limpo is None else limpo"),
    ("py: os posicionais nao contam", "py", LOG_PY,
     "        for _ in posicionais:\n            rejeicoes.append((MOTIVO_MENSAGEM, \"<posicional>\"))\n", ""),
    ("py: o modo estrito nao levanta", "py", LOG_PY,
     "        if rejeicoes and self._estrito:\n            raise CampoRejeitado(rejeicoes)\n", ""),
    ("py: o modo estrito levanta depois de escrever", "py", LOG_PY,
     "        if rejeicoes and self._estrito:\n            raise CampoRejeitado(rejeicoes)\n        for motivo, _nome in rejeicoes:",
     "        self._escrever(\"{}\")\n        if rejeicoes and self._estrito:\n            raise CampoRejeitado(rejeicoes)\n        for motivo, _nome in rejeicoes:"),
    ("py: as rejeicoes nao sao contadas", "py", LOG_PY,
     '            CONTADORES.incrementar(f"{METRICA_REJEITADOS}:{motivo}")', "            pass"),
    ("py: excepcao regista a mensagem como outcome", "py", LOG_PY,
     '        campos["error_code"] = codigo_com_classe(codigo, type(erro).__name__)',
     '        campos["error_code"] = codigo_com_classe(codigo, type(erro).__name__)\n        campos["outcome"] = str(erro)'),
    ("py: excepcao sem a classe", "py", LOG_PY,
     '        campos["error_code"] = codigo_com_classe(codigo, type(erro).__name__)',
     '        campos["error_code"] = codigo'),
    ("py: o nome do servico nao e validado", "py", LOG_PY,
     "        canonico = validar_svc(svc)\n        if canonico is None:",
     "        canonico = svc\n        if canonico is None:"),
    ("py: parametros por nome colidem com campos", "py", LOG_PY,
     "    def info(self, /, *posicionais, **campos) -> None:",
     "    def info(self, *posicionais, **campos) -> None:"),
    ("py: o modo estrito liga-se com qualquer valor", "py", LOG_PY,
     '            estrito = os.environ.get(VARIAVEL_ESTRITO, "") == "1"',
     '            estrito = os.environ.get(VARIAVEL_ESTRITO, "") != ""'),
    ("py: o ts sai na hora local", "py", LOG_PY,
     "    utc = instante.astimezone(datetime.timezone.utc)", "    utc = instante"),
    # Fora da lista, por serem equivalentes: retirar a validacao da forma do
    # `ts` (Python e TypeScript). O tipo exacto do instante ja garante a forma
    # — `datetime` exacto num lado, `Date.prototype.toISOString` no outro — e
    # a validacao fica como segunda camada (um `strftime("%Y")` que nao enche
    # o ano a quatro digitos, por exemplo). Registado em `ANALISE-11` §3.2.
    # ---------------------------------------------------------------- ponte (Python)
    ("py: a ponte escreve a mensagem da biblioteca", "py", PONTE,
     '                {"outcome": OUTCOME_BIBLIOTECA, "error_code": codigo},',
     '                {"outcome": record.getMessage(), "error_code": codigo},'),
    ("py: a ponte usa o logger estrito", "py", PONTE,
     "        self._registo = registo.tolerante()", "        self._registo = registo"),
    ("py: a ponte deixa o handleError de origem", "py", PONTE,
     "    def handleError(self, record: logging.LogRecord) -> None:",
     "    def _handleError_desligado(self, record: logging.LogRecord) -> None:"),
    ("py: a ponte deixa subir a excepcao", "py", PONTE,
     "        except Exception:\n            # Uma excepcao que saisse daqui", "        except ZeroDivisionError:\n            # Uma excepcao que saisse daqui"),
    ("py: a ponte nao tira os manipuladores que la estavam", "py", PONTE,
     "    for existente in list(raiz.handlers):\n        raiz.removeHandler(existente)\n", ""),
    ("py: sem gancho no fio principal", "py", PONTE, "    sys.excepthook = gancho\n", ""),
    ("py: sem gancho nos outros fios", "py", PONTE, "    threading.excepthook = gancho_de_fio\n", ""),
    ("py: sem gancho nos destrutores", "py", PONTE, "    sys.unraisablehook = gancho_de_destrutor\n", ""),
    ("py: os warnings nao passam pela ponte", "py", PONTE, "    logging.captureWarnings(True)\n", ""),
    ("py: a ponte perde a classe da excepcao", "py", PONTE,
     "                codigo = codigo_com_classe(codigo, record.exc_info[0].__name__)",
     "                pass"),
    # ---------------------------------------------------------------- politica (TypeScript)
    ('ts: sem a regra dos sete digitos', 'ts', POL_TS, '  if ((texto.match(DIGITO)?.length ?? 0) > DIGITOS_MAXIMOS) {\n    return false;\n  }\n', ''),
    ('ts: digitos so contam se forem seguidos', 'ts', POL_TS, '  if ((texto.match(DIGITO)?.length ?? 0) > DIGITOS_MAXIMOS) {', '  if (/[0-9](?:[^A-Za-z0-9]?[0-9]){6}/.test(texto)) {'),
    ('ts: sem as formas de segredo', 'ts', POL_TS, '  return !FORMA_DE_SEGREDO.test(texto);', '  return true;'),
    ('ts: oito digitos em vez de sete', 'ts', POL_TS, 'export const DIGITOS_MAXIMOS = 6;', 'export const DIGITOS_MAXIMOS = 7;'),
    ('ts: a mascara corta por unidades UTF-16', 'ts', POL_TS, '  const compacta = Array.from(referencia.replace(BRANCOS, ""));', '  const compacta = referencia.replace(BRANCOS, "").split("");'),
    ('ts: o valor de um campo reservado vai na mensagem estrita', 'ts', LOG_TS, '        rejeicoes.push([MOTIVO_RESERVADO, nome]);', '        rejeicoes.push([MOTIVO_RESERVADO, String(valor)]);'),
    ('ts: sem a rede de registar', 'ts', LOG_TS, '      CONTADORES.incrementar(METRICA_ESCRITA_FALHADA);\n    }\n  }\n\n  #registar(', '      throw erro;\n    }\n  }\n\n  #registar('),
    ('ts: o relogio usa o toISOString do objecto', 'ts', LOG_TS, '    const ts: unknown = Date.prototype.toISOString.call(this.#relogio());', '    const ts: unknown = this.#relogio().toISOString();'),
    ('ts: posicionais que nao sao uma lista lancam', 'ts', LOG_TS, '    const quantos = Array.isArray(posicionais)\n      ? posicionais.length\n      : posicionais === undefined || posicionais === null\n        ? 0\n        : 1;', '    const quantos = (posicionais as unknown[]).length;'),
    ('ts: um aviso do processo sai com o texto de origem', 'ts', LOG_TS, '  processo.removeAllListeners("warning");\n', ''),
    ('ts: o aviso do processo leva a mensagem', 'ts', LOG_TS, '      error_code: codigoComClasse(CODIGO_AVISO, classeDe(aviso)),', '      error_code: codigoComClasse(CODIGO_AVISO, classeDe(aviso)),\n      tool: (aviso as Error)?.message,'),
    ('ts: o gancho de erro leva a mensagem', 'ts', LOG_TS, '      error_code: codigoComClasse(CODIGO_NAO_TRATADA, classeDe(erro)),', '      error_code: codigoComClasse(CODIGO_NAO_TRATADA, classeDe(erro)),\n      tool: (erro as Error)?.message,'),
    ("ts: identificador sem ancora no fim", "ts", POL_TS,
     "const IDENTIFICADOR = new RegExp(`^${PALAVRA}(?:_(?:${PALAVRA}|${NUMERO}))*$`);",
     "const IDENTIFICADOR = new RegExp(`^${PALAVRA}(?:_(?:${PALAVRA}|${NUMERO}))*`);"),
    ("ts: identificador com digitos em qualquer sitio", "ts", POL_TS,
     'const PALAVRA = "[a-z]+[0-9]{0,3}";', 'const PALAVRA = "[a-z][a-z0-9]*";'),
    ("ts: identificador sem limite de comprimento", "ts", POL_TS,
     "  if (valor.length < 1 || valor.length > maximo) {\n    return null;\n  }\n  if (!forma.test(valor) || !semConteudo(valor)) {",
     "  if (!forma.test(valor) || !semConteudo(valor)) {"),
    ("ts: tenant_id aceita qualquer texto", "ts", POL_TS,
     "  return UUID.test(minusculas) ? minusculas : null;", "  return minusculas;"),
    ("ts: msg_id e turn_id aceitam um wamid em claro", "ts", POL_TS,
     '  if (typeof valor === "string" && ID_OPACO.test(valor)) {\n    return valor;\n  }\n  return null;',
     '  if (typeof valor === "string") {\n    return valor;\n  }\n  return null;'),
    ("ts: contact_hmac_prefix sem forma", "ts", POL_TS,
     '      return typeof valor === "string" && HMAC_PREFIXO.test(valor) ? valor : null;',
     '      return typeof valor === "string" ? valor : null;'),
    ("ts: latency_ms sem tecto", "ts", POL_TS,
     "        valor >= 0 &&\n        valor <= LATENCIA_MAXIMA_MS\n", "        valor >= 0\n"),
    ("ts: latency_ms aceita fraccoes", "ts", POL_TS,
     "        Number.isInteger(valor) &&\n", ""),
    ("ts: error_code sem forma no codigo", "ts", POL_TS,
     "  if (!CODIGO.test(codigo) || !semConteudo(codigo)) {", "  if (!semConteudo(codigo)) {"),
    ("ts: error_code sem validar a classe", "ts", POL_TS,
     "  if (corte !== -1 && !classeValida(valor.slice(corte + 1))) {\n    return null;\n  }\n", ""),
    ("ts: classe sem limite de grupos de digitos", "ts", POL_TS,
     "  return grupos.length <= 2 && grupos.every((grupo) => grupo.length <= 4);", "  return true;"),
    ("ts: nomeLegivel devolve qualquer nome", "ts", POL_TS,
     "    nome.length <= NOME_LEGIVEL_MAXIMO &&\n    NOME_LEGIVEL.test(nome)\n", "    true\n"),
    ("ts: idOpaco devolve a entrada", "ts", POL_TS,
     "  return `m_${resumo.slice(0, 32)}`;", "  return identificador;"),
    ("ts: a mascara mostra quatro caracteres", "ts", POL_TS,
     "export const REFERENCIA_VISIVEIS = 3;", "export const REFERENCIA_VISIVEIS = 4;"),
    ("ts: a allowlist ganha um campo", "ts", POL_TS,
     '  "outcome",\n  "error_code",\n] as const;\n\nexport const NIVEIS',
     '  "outcome",\n  "error_code",\n  "mensagem",\n] as const;\n\nexport const NIVEIS'),
    # ---------------------------------------------------------------- logger (TypeScript)
    ("ts: um campo desconhecido passa em claro", "ts", LOG_TS,
     "        rejeicoes.push([MOTIVO_DESCONHECIDO, nomeLegivel(nome)]);\n      } else {",
     "        this.#escrever(JSON.stringify({ [nome]: valor }));\n      } else {"),
    ("ts: um campo desconhecido e ignorado sem contar", "ts", LOG_TS,
     "        rejeicoes.push([MOTIVO_DESCONHECIDO, nomeLegivel(nome)]);\n      } else {",
     "        continue;\n      } else {"),
    ("ts: os campos reservados podem ser dados", "ts", LOG_TS,
     "      if (RESERVADOS.includes(nome)) {", "      if (false) {"),
    ("ts: um valor invalido passa em claro", "ts", LOG_TS,
     "        if (limpo === null) {\n          rejeicoes.push([MOTIVO_VALOR, nome]);\n        } else {\n          aceites.set(nome, limpo);\n        }",
     "        aceites.set(nome, limpo === null ? (valor as string) : limpo);"),
    ("ts: a linha leva tudo o que foi aceite", "ts", LOG_TS,
     "    for (const nome of DE_CHAMADA) {\n      const valor = aceites.get(nome);\n      if (valor !== undefined) {\n        linha[nome] = valor;\n      }\n    }",
     "    for (const [nome, valor] of aceites) {\n      linha[nome] = valor;\n    }"),
    ("ts: um texto no lugar dos campos nao conta", "ts", LOG_TS,
     "        rejeicoes.push([MOTIVO_MENSAGEM, \"<posicional>\"]);\n      } else {\n        this.#separar(",
     "      } else {\n        this.#separar("),
    ("ts: o modo estrito nao lanca", "ts", LOG_TS,
     "    if (rejeicoes.length > 0 && this.estrito) {\n      throw new CampoRejeitadoError(rejeicoes);\n    }\n", ""),
    ("ts: as rejeicoes nao sao contadas", "ts", LOG_TS,
     "      CONTADORES.incrementar(`${METRICA_REJEITADOS}:${motivo}`);", "      void motivo;"),
    ("ts: excepcao regista a mensagem como outcome", "ts", LOG_TS,
     "    dados.error_code = codigoComClasse(codigo, classeDe(erro));",
     "    dados.error_code = codigoComClasse(codigo, classeDe(erro));\n    dados.outcome = (erro as Error)?.message;"),
    ("ts: a classe vem de erro.name", "ts", LOG_TS,
     "    const construtor: unknown = Object.getPrototypeOf(erro)?.constructor;\n    if (typeof construtor === \"function\") {\n      return construtor.name;\n    }",
     "    return (erro as Error).name;"),
    ("ts: um getter que lanca derruba a chamada", "ts", LOG_TS,
     "      try {\n        valor = campos[nome];\n      } catch {",
     "      valor = campos[nome];\n      try {\n      } catch {"),
    ("ts: o nome do servico nao e validado", "ts", LOG_TS,
     "    const canonico = validarSvc(svc);", "    const canonico: string | null = svc;"),
    ("ts: um erro por tratar nao termina o processo", "ts", LOG_TS,
     "    processo.exit(1);\n", ""),
    ("ts: sem gancho nas promessas rejeitadas", "ts", LOG_TS,
     '  processo.on("unhandledRejection", naoTratada);\n', ""),
    # Fora da lista, por ser equivalente: os ganchos do processo usarem o
    # logger estrito. O que eles escrevem (`excepcao_nao_tratada[:Classe]`) e
    # sempre valido, pelo que o modo estrito nunca chega a disparar; o
    # `tolerante()` fica por defesa. Do lado Python a ponte **nao** e
    # equivalente (o nome do logger vem de fora) e a mutacao esta na lista.
    # ---------------------------------------------------------------- tipos (TypeScript)
    ('tsc: os campos deixam de ser exactos', 'tsc', LOG_TS, '  : { readonly [K in keyof T]: K extends keyof Permitidos ? Permitidos[K] : never };', '  : { readonly [K in keyof T]: K extends keyof Permitidos ? Permitidos[K] : unknown };'),
    ('tsc: um object sem chaves volta a passar', 'tsc', LOG_TS, 'export type SoCampos<T, Permitidos = CamposDeLog> = [keyof T] extends [never]', 'export type SoCampos<T, Permitidos = CamposDeLog> = [T] extends [never]'),
    # Fora da lista, por ser equivalente: trocar `<T extends object>` por `<T>`.
    # Um texto, um numero e uma lista continuam a nao compilar sem a restricao
    # (o tipo mapeado ja os recusa); ela fica por defesa, e nenhum caso
    # conhecido a distingue. Registado em `docs/analises/ANALISE-11`.
    ("tsc: info aceita um objecto com chaves a mais", "tsc", LOG_TS,
     "  info<T extends object>(campos?: SoCampos<T>): void {",
     "  info(campos?: CamposDeLog): void {"),
    ("tsc: excepcao aceita error_code nos campos", "tsc", LOG_TS,
     "    campos?: SoCampos<T, CamposDeErro>,", "    campos?: SoCampos<T>,"),
    ("tsc: latency_ms passa a aceitar texto", "tsc", POL_TS,
     "  readonly latency_ms?: number;", "  readonly latency_ms?: number | string;"),
    ("tsc: a interface ganha um campo de texto", "tsc", POL_TS,
     "  readonly error_code?: string;\n}", "  readonly error_code?: string;\n  readonly texto?: string;\n}"),
    # ---------------------------------------------------------------- X-11
    ('x11: sem o padrao do telefone nacional', 'py', X11, '    (TELEFONE_NACIONAL, re.compile(rf"9(?:{_ENTRE}[0-9]){{8}}")),\n', ''),
    ('x11: sem o padrao do telefone internacional', 'py', X11, '        re.compile(rf"(?:\\+|00)?244{_SEP}{{0,3}}9(?:{_ENTRE}[0-9]){{8}}"),', '        re.compile(r"NUNCA-BATE-EM-NADA"),'),
    ('x11: o telefone so e visto sem separadores', 'py', X11, '    (TELEFONE_NACIONAL, re.compile(rf"9(?:{_ENTRE}[0-9]){{8}}")),', '    (TELEFONE_NACIONAL, re.compile(r"9[0-9]{8}")),'),
    ('x11: so um separador entre digitos', 'py', X11, '_ENTRE = rf"{_SEP}{{0,2}}"', '_ENTRE = rf"{_SEP}?"'),
    ('x11: o separador e so espaco, ponto e hifen', 'py', X11, '_SEP = r"[^0-9A-Za-z]"', '_SEP = r"[\\s.\\-()]"'),
    ('x11: sem normalizar digitos e invisiveis', 'py', X11, '    texto = normalizar(texto)\n    nomes: list[str] = []', '    nomes: list[str] = []'),
    ('x11: uma chave repetida esconde a primeira', 'py', X11, '        objecto = json.loads(texto, object_pairs_hook=_Pares)', '        objecto = json.loads(texto, object_pairs_hook=lambda p: _Pares(dict(p).items()))'),
    ("x11: sem o padrao do e-mail", "py", X11,
     '    (EMAIL, re.compile(r"[A-Za-z0-9._%+\\-]+@[A-Za-z0-9\\-]+(?:\\.[A-Za-z0-9\\-]+)+")),\n', ""),
    ('x11: sem o padrao do IBAN', 'py', X11, '    (IBAN_AO, re.compile(rf"AO[0-9]{{2}}(?:{_ENTRE}[0-9]){{21}}")),\n', ''),
    ('x11: sem a sequencia de digitos', 'py', X11, '    (SEQUENCIA_DE_DIGITOS, re.compile(rf"[0-9](?:{_ENTRE}[0-9]){{8}}")),\n', ''),
    ("x11: o padrao do NIF e ignorado", "py", X11,
     "    for expressao in configuracao.nif_padroes:\n        if expressao.search(texto):\n            acrescentar(NIF)\n", ""),
    ("x11: os canarios nao sao procurados", "py", X11,
     "    for canario in configuracao.canarios:\n        if canario in texto:\n            acrescentar(CANARIO)\n", ""),
    ("x11: os segredos nao sao procurados", "py", X11,
     '        if padrao.classe in ("chave_api", "chave_privada") and padrao.expressao.search(texto):\n            acrescentar(SEGREDO)',
     "        pass"),
    ("x11: nao descodifica base64", "py", X11,
     "        for descodificado in _descodificacoes(texto):", "        for descodificado in ():"),
    ("x11: um campo de forma fechada nunca e varrido", "py", X11,
     "        if formas and isinstance(valor, str) and any(f.fullmatch(valor) for f in formas):",
     "        if formas and isinstance(valor, str):"),
    ("x11: a forma fechada confere-se com `match`", "py", X11,
     "        if formas and isinstance(valor, str) and any(f.fullmatch(valor) for f in formas):",
     "        if formas and isinstance(valor, str) and any(f.match(valor) for f in formas):"),
    ("x11: varrimento cego (sem formas fechadas)", "py", X11,
     "        formas = FORMAS_FECHADAS.get(chave)", "        formas = None"),
    ("x11: um campo fora da allowlist nao e achado", "py", X11,
     "            achados.append((CAMPO_FORA, legivel))\n", ""),
    ("x11: uma linha que nao e JSON nao e varrida", "py", X11,
     '        achados += [(nome, "<linha>") for nome in padroes_no_texto(texto, configuracao)]\n', ""),
    ("x11: uma linha que nao e JSON nao e desvio", "py", X11,
     '        achados = [(LINHA_FORA, "<linha>")]', "        achados = []"),
    ("x11: as chaves nao sao varridas", "py", X11,
     '            for nome in padroes_no_texto(chave, configuracao):\n                achados.append((nome, "<chave>"))\n', ""),
    ("x11: o achado repete a chave tal como veio", "py", X11,
     '    return chave if _CHAVE_LEGIVEL.fullmatch(chave) else "<chave ilegivel>"', "    return chave"),
    # ---------------------------------------------------------------- lint
    ('lint: sem a regra do console', 'py', LINT, '        (CONSOLE, _CONSOLE),\n', ''),
    ('lint: sem a regra do stdout em TS', 'py', LINT, '        (STDOUT, _PROCESS_STD),\n', ''),
    ('lint: sem a regra do registar em TS', 'py', LINT, '        (REGISTAR, _REGISTAR),\n', ''),
    ('lint: o stdout so conta depois de `process.`', 'py', LINT, '_PROCESS_STD = re.compile(r"(?<![A-Za-z0-9_$])(?:stdout|stderr|emitWarning)(?![A-Za-z0-9_$])")', '_PROCESS_STD = re.compile(r"process\\.(?:stdout|stderr)(?![A-Za-z0-9_$])")'),
    ('lint: emitWarning passa', 'py', LINT, '(?:stdout|stderr|emitWarning)', '(?:stdout|stderr)'),
    ('lint: uma regex com barras abre comentario', 'py', LINT, '        escapada = i > 0 and fonte[i - 1] == "\\\\"', '        escapada = False'),
    ('lint: um comentario por fechar passa calado', 'py', LINT, '                raise ComentarioPorFechar(i, fonte.count("\\n", 0, i) + 1)\n            fim += 2', '                fim = n - 2\n            fim += 2'),
    ('lint: so `src/` esta no ambito', 'py', LINT, '            subpastas[:] = sorted(s for s in subpastas if s not in IGNORADOS)', '            subpastas[:] = sorted(s for s in subpastas if s not in IGNORADOS)\n            if "src" not in Path(pasta).parts:\n                continue'),
    ('lint: os testes entram no ambito', 'py', LINT, 'IGNORADOS = ("node_modules", "dist", "__pycache__", ".venv", "tests")', 'IGNORADOS = ("node_modules", "dist", "__pycache__", ".venv")'),
    ("lint: `globalThis.console` escapa", "py", LINT,
     '_CONSOLE = re.compile(r"(?<![A-Za-z0-9_$])console(?![A-Za-z0-9_$])")',
     '_CONSOLE = re.compile(r"(?<![A-Za-z0-9_$.])console(?![A-Za-z0-9_$])")'),
    ("lint: os comentarios nao sao retirados", "py", LINT,
     "    limpa = sem_comentarios(fonte)", "    limpa = fonte"),
    ("lint: sem a regra do print", "py", LINT,
     "        if isinstance(no, ast.Name) and no.id in _NOMES_DE_PRINT:\n            achados.append((no.lineno, PRINT))\n        elif isinstance(no, ast.Import):",
     "        if isinstance(no, ast.Import):"),
    ('lint: sem a regra do logging', 'py', LINT, '                if raiz in _MODULOS_DE_LOGGING:\n                    achados.append((no.lineno, LOGGING))\n                elif raiz in _MODULOS_DE_PRINT:', '                if raiz in _MODULOS_DE_PRINT:'),
    ('lint: loguru e structlog passam', 'py', LINT, '_MODULOS_DE_LOGGING = ("logging", "loguru", "structlog")', '_MODULOS_DE_LOGGING = ("logging",)'),
    ('lint: sem a regra do traceback', 'py', LINT, '                elif raiz == "traceback":\n                    achados.append((no.lineno, TRACEBACK))\n        elif isinstance(no, ast.ImportFrom):', '        elif isinstance(no, ast.ImportFrom):'),
    ('lint: sem a regra da saida com texto', 'py', LINT, '            if _saida_com_texto(no):\n                achados.append((no.lineno, SAIDA))\n', ''),
    ('lint: a saida com f-string passa', 'py', LINT, '    if isinstance(no, (ast.JoinedStr, ast.BinOp)):\n        return True\n', ''),
    ('lint: sem a regra do registar em Python', 'py', LINT, '            if isinstance(no.func, ast.Attribute) and no.func.attr == "registar":\n                achados.append((no.lineno, REGISTAR))\n', ''),
    ('lint: sem a regra do stdout em Python', 'py', LINT, '            # mesmo modulo. O `stdout` de um `subprocess` tambem bate.\n            achados.append((no.lineno, STDOUT))', '            # mesmo modulo. O `stdout` de um `subprocess` tambem bate.\n            pass'),
    ('lint: o stdout so conta em `sys`', 'py', LINT, '            # mesmo modulo. O `stdout` de um `subprocess` tambem bate.\n            achados.append((no.lineno, STDOUT))', '            # mesmo modulo. O `stdout` de um `subprocess` tambem bate.\n            if isinstance(no.value, ast.Name) and no.value.id == "sys":\n                achados.append((no.lineno, STDOUT))'),
    ("lint: um ficheiro que nao se analisa passa", "py", LINT,
     "    except (SyntaxError, ValueError):\n        return [(1, ILEGIVEL)]",
     "    except (SyntaxError, ValueError):\n        return []"),
    ("lint: a isencao apanha os vizinhos do logger", "py", LINT,
     '    "packages/core-ts/src/logger/",\n', '    "packages/core-ts/src/logger",\n'),
    ("lint: os pacotes ficam fora do ambito", "py", LINT,
     'RAIZES = ("services", "packages", "libs")', 'RAIZES = ("services", "libs")'),
    ("lint: passa sem ter lido codigo de uma linguagem", "py", LINT,
     '    if lidos["ts"] == 0 or lidos["py"] == 0:', "    if False:"),
    ("lint: o canario nao exige as regras obrigatorias", "py", LINT,
     "            if regra not in vistas[linguagem]:", "            if False:"),
    ("lint: o canario aceita uma negativa com a regra errada", "py", LINT,
     "        if regras != {esperada}:", "        if not regras:"),
    # ---------------------------------------------------------------- primeira revisao (recebida depois do merge)
    ('rev1: a ponte poe a mensagem num campo quando tem cara de identificador', 'py', PONTE, '                {"outcome": OUTCOME_BIBLIOTECA, "error_code": codigo},', '                {"outcome": record.msg if isinstance(record.msg, str) and record.msg.isidentifier() else OUTCOME_BIBLIOTECA, "error_code": codigo},'),
    ('rev1: a ponte deixa passar campos validos do extra', 'py', PONTE, '                {"outcome": OUTCOME_BIBLIOTECA, "error_code": codigo},', '                {"outcome": OUTCOME_BIBLIOTECA, "error_code": codigo, **{k: v for k, v in vars(record).items() if k in ("tool", "wa_type", "latency_ms", "tenant_id")}},'),
    ('rev1: o gancho do Node tambem escreve o erro na consola', 'ts', LOG_TS, '  const naoTratada = (erro: unknown): void => {\n', '  const naoTratada = (erro: unknown): void => {\n    console.error(erro);\n'),
    ('rev1: o logger sai do estrato critico', 'py', "ci/thresholds.yaml", '      - "*/logger/*"\n', ''),
    ('rev1: um objecto com classe conta como campos (TS)', 'ts', LOG_TS, '  return prototipo === Object.prototype || prototipo === null;', '  return true;'),
    ('rev1: a amostra aceita um log vazio', 'py', AMOSTRA, '        if not linhas:\n            raise ConfiguracaoInvalida(', '        if False:\n            raise ConfiguracaoInvalida('),
    ('rev1: o lint deixa passar uvicorn com registo proprio', 'py', LINT, '            if _uvicorn_com_registo_proprio(no):\n                achados.append((no.lineno, UVICORN))\n', ''),
    ('rev1: o lint so ve uvicorn sem o argumento', 'py', LINT, '            return not (isinstance(argumento.value, ast.Constant) and argumento.value.value is None)', '            return False'),
    ('rev1: o lint deixa passar bibliotecas de registo de Node', 'py', LINT, '        (LOGGING, _BIBLIOTECAS_TS),\n', ''),
    ('rev1: o lint deixa passar o middleware hono/logger', 'py', LINT, '|morgan|debug|hono/logger)', '|morgan|debug)'),
    ('rev1: as fixtures de forma nao levam o telefone como inteiro', 'py', GERADOR, '            campos["latency_ms"] = numero\n', ''),
    ('rev1: a linha de comandos nao junta as fixtures de forma', 'py', CLI, '    if argumentos.quantas == gerador.QUANTAS:', '    if False:'),
    # ---------------------------------------------------------------- cablagem
    ('cablagem: o gate 2 sem o lint dos logs', 'py', "Makefile", '\t@$(MAKE) log-lint\n', ''),
    ('cablagem: o gate 6 sem o x11', 'py', "Makefile", '\t@$(MAKE) x11\n', ''),
    ('cablagem: o lint dos logs sem canario', 'py', "Makefile", '\t@$(PYTHON) -m log_policy --root $(ROOT) canario\n', ''),
    ('cablagem: o x11 sem comparar contadores', 'py', "Makefile", '\t@$(PYTHON) -m log_policy iguais $(X11_DIR)/py.contadores.json $(X11_DIR)/ts.contadores.json\n', ''),
    ('cablagem: o x11 sem comparar as linguagens', 'py', "Makefile", '\t@$(PYTHON) -m log_policy iguais $(X11_DIR)/py.log $(X11_DIR)/ts.log\n', ''),
    ('cablagem: o x11 sem contar as linhas', 'py', "Makefile", ' --linhas-esperadas 1030', ''),
    ('cablagem: um servico sem o tratador de erro', 'py', "services/gwy/src/app.ts", '    log?.excepcao(erro, "tratador_falhou");\n', ''),
    ('cablagem: um servico sem passar o logger a aplicacao', 'py', "services/com/src/server.ts", 'createApp(log).fetch', 'createApp().fetch'),
    # ---------------------------------------------------------------- cli e gerador
    ("cli: o controlo positivo nao falha o x11", "py", CLI,
     "            if total == 0 or vistas != total:", "            if False:"),
    ("cli: o numero de linhas nao e conferido", "py", CLI,
     "        if argumentos.linhas_esperadas is not None and linhas != argumentos.linhas_esperadas:",
     "        if False:"),
    ("cli: zero linhas e um resultado", "py", CLI, "    if total_linhas == 0:", "    if False:"),
    ("cli: o x11 sai com 0 havendo achados", "py", CLI,
     "    return 1 if achados or falhou else 0", "    return 1 if falhou else 0"),
    ("cli: o lint sai com 0 havendo achados", "py", CLI,
     '        f"{len(achados)} achado(s)"\n    )\n    return 1 if achados else 0',
     '        f"{len(achados)} achado(s)"\n    )\n    return 0'),
    ("cli: iguais nao compara", "py", CLI, "    if a == b:", "    if True:"),
    ("gerador: nao exige todas as combinacoes", "py", GERADOR,
     "    if em_falta:\n        raise AssertionError(", "    if False:\n        raise AssertionError("),
    ("amostra: uma pasta sem logs da zero", "py", AMOSTRA,
     "    if not ficheiros:\n        raise ConfiguracaoInvalida(", "    if False:\n        raise ConfiguracaoInvalida("),
    ("amostra: amostra tudo em vez de N linhas", "py", AMOSTRA,
     "        amostra = linhas if len(linhas) <= quantas else sorteio.sample(linhas, quantas)",
     "        amostra = linhas"),
    ("amostra: os desvios de formato contam como identificadores", "py", AMOSTRA,
     "        identificadores = sum(n for padrao, n in por_padrao.items() if padrao not in DE_FORMATO)",
     "        identificadores = sum(por_padrao.values())"),
]

COPIAR = ("libs", "packages", "services", "tools", "tsconfig.base.json", "Makefile",
          "ci/thresholds.yaml",
          "docs/tecnica/08_Seguranca_Conformidade.md")
IGNORAR = shutil.ignore_patterns("node_modules", "dist", "__pycache__", ".venv", "*.egg-info")

TSCONFIG = """{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "noEmit": true,
    "allowImportingTsExtensions": true,
    "typeRoots": ["TIPOS"],
    "types": ["node"]
  },
  "include": ["src/logger/**/*.ts", "src/tenant_guard/**/*.ts", "tests/logger.test.ts", "tests/x11_conduzir.ts"]
}
"""


def _copiar(destino: Path) -> None:
    for relativo in COPIAR:
        origem, alvo = RAIZ / relativo, destino / relativo
        alvo.parent.mkdir(parents=True, exist_ok=True)
        if origem.is_dir():
            shutil.copytree(origem, alvo, ignore=IGNORAR)
        else:
            shutil.copy(origem, alvo)


def _ambiente(copia: Path) -> dict[str, str]:
    ambiente = dict(os.environ)
    ambiente["PYTHONPATH"] = os.pathsep.join(
        str(copia / parte) for parte in ("tools", "libs/py-core/src")
    )
    ambiente["PYTHONDONTWRITEBYTECODE"] = "1"
    ambiente.pop("KAMBA_LOG_ESTRITO", None)
    return ambiente


def _testes_py(ficheiro: str) -> list[list[str]]:
    """As baterias que uma mutacao a `ficheiro` tem de por vermelhas."""
    base = [sys.executable, "-m", "unittest", "discover"]
    logger = base + ["-s", "libs/py-core/tests", "-t", "libs/py-core/tests", "-p", "test_logger*.py"]

    def ferramenta(padrao: str) -> list[str]:
        return base + ["-s", "tools/log_policy/tests", "-t", "tools", "-p", padrao]

    if ficheiro.startswith("libs/"):
        return [logger, ferramenta("test_x11.py")]
    if ficheiro == "Makefile" or ficheiro.startswith(("services/", "ci/")):
        return [ferramenta("test_cablagem.py")]
    if ficheiro == LINT:
        return [ferramenta("test_lint.py")]
    return [ferramenta("test_x11.py"), ferramenta("test_amostra_e_cli.py")]


def _correr_py(copia: Path, ficheiro: str) -> bool:
    """`True` se todas as baterias passarem."""
    for comando in _testes_py(ficheiro):
        resultado = subprocess.run(comando, cwd=copia, env=_ambiente(copia), capture_output=True)
        if resultado.returncode != 0:
            return False
    return True


class SemNode(RuntimeError):
    pass


def _node(copia: Path, argumentos: list[str], docker: str | None, com_repositorio: bool = False):
    """Corre `node <argumentos>` em `packages/core-ts` da copia."""
    if docker:
        comando = ["docker", "run", "--rm", "-v", f"{copia}:/c"]
        if com_repositorio:
            comando += ["-v", f"{RAIZ}:/repo:ro"]
        comando += ["-w", "/c/packages/core-ts", docker, "node", *argumentos]
        ambiente = dict(os.environ, MSYS_NO_PATHCONV="1")
        return subprocess.run(comando, capture_output=True, env=ambiente)
    if shutil.which("node") is None:
        raise SemNode()
    return subprocess.run(
        ["node", *argumentos], cwd=copia / "packages/core-ts", capture_output=True
    )


def _correr_ts(copia: Path, docker: str | None) -> bool:
    return _node(copia, ["--test", "tests/logger.test.ts"], docker).returncode == 0


def _correr_tsc(copia: Path, docker: str | None) -> bool:
    raiz_no_node = "/repo" if docker else str(RAIZ)
    config = copia / "packages/core-ts/tsconfig.mutacoes.json"
    config.write_text(
        TSCONFIG.replace("TIPOS", f"{raiz_no_node}/node_modules/@types".replace("\\", "/")),
        encoding="utf-8",
    )
    # `lexists`, e so sobre a pasta: instalado num contentor Linux, o que la
    # esta dentro sao ligacoes simbolicas que o Windows nao consegue seguir.
    if not os.path.lexists(RAIZ / "node_modules"):
        raise SemNode()
    resultado = _node(
        copia,
        [f"{raiz_no_node}/node_modules/typescript/bin/tsc", "-p", "tsconfig.mutacoes.json"],
        docker,
        com_repositorio=True,
    )
    return resultado.returncode == 0


def _passa(copia: Path, corredor: str, ficheiro: str, docker: str | None) -> bool:
    if corredor == "py":
        return _correr_py(copia, ficheiro)
    if corredor == "ts":
        return _correr_ts(copia, docker)
    return _correr_tsc(copia, docker)


def aplicaveis() -> int:
    falhas = 0
    for nome, _corredor, ficheiro, velho, novo in MUTACOES:
        texto = (RAIZ / ficheiro).read_text(encoding="utf-8")
        if texto.count(velho) != 1 or velho == novo:
            print(f"MUTACAO NAO APLICAVEL ({texto.count(velho)} ocorrencias): {nome}")
            falhas += 1
    print(f"{len(MUTACOES)} mutacoes, {falhas} nao aplicaveis")
    return 1 if falhas else 0


def main(argv: list[str]) -> int:
    if "--aplicaveis" in argv:
        return aplicaveis()
    docker = None
    if "--docker" in argv:
        posicao = argv.index("--docker")
        docker = argv[posicao + 1]
        argv = argv[:posicao] + argv[posicao + 2 :]
    filtro = argv[0] if argv else ""
    escolhidas = [m for m in MUTACOES if filtro in m[0]]
    if aplicaveis() != 0:
        return 1

    copia = Path(tempfile.mkdtemp(prefix="kam068-mutacoes-"))
    try:
        _copiar(copia)
        assert RAIZ not in copia.parents, "a copia tem de ficar fora do repositorio"
        print(f"copia em {copia}")

        por_correr: set[str] = set()
        corredores = sorted({m[1] for m in escolhidas})
        for corredor in corredores:
            ficheiros = sorted({m[2] for m in escolhidas if m[1] == corredor})
            for ficheiro in ficheiros if corredor == "py" else ficheiros[:1]:
                try:
                    verde = _passa(copia, corredor, ficheiro, docker)
                except SemNode:
                    por_correr.add(corredor)
                    break
                if not verde:
                    print(f"LINHA DE BASE VERMELHA ({corredor}, {ficheiro}): nada foi provado")
                    return 1
        print(f"linha de base verde ({', '.join(c for c in corredores if c not in por_correr)})")

        apanhadas, sobreviventes, saltadas = 0, [], 0
        for nome, corredor, ficheiro, velho, novo in escolhidas:
            if corredor in por_correr:
                print(f"  POR CORRER   {nome}")
                saltadas += 1
                continue
            alvo = copia / ficheiro
            original = alvo.read_bytes()
            alvo.write_bytes(original.decode("utf-8").replace(velho, novo).encode("utf-8"))
            try:
                verde = _passa(copia, corredor, ficheiro, docker)
            finally:
                alvo.write_bytes(original)
            if verde:
                print(f"  SOBREVIVEU   {nome}")
                sobreviventes.append(nome)
            else:
                print(f"  apanhada     {nome}")
                apanhadas += 1
        print(
            f"\n{len(escolhidas)} mutacoes: {apanhadas} apanhadas, "
            f"{len(sobreviventes)} sobreviventes, {saltadas} por correr"
        )
        if saltadas:
            print("  sem `node` (use --docker <imagem>): as mutacoes `ts`/`tsc` NAO foram provadas")
        return 0 if not sobreviventes and not saltadas else 1
    finally:
        shutil.rmtree(copia, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
