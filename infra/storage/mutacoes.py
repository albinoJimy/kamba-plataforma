#!/usr/bin/env python3
"""Prova por mutacao dos testes de armazenamento (KAM-011), uma alteracao por execucao.

    python infra/storage/mutacoes.py [filtro]
    python infra/storage/mutacoes.py --aplicaveis

Um teste que passa nao prova que morde. Isto prova: copia `libs/py-core` e
`packages/core-ts` para um directorio temporario **fora do repositorio**, corre
as suites de armazenamento nessa copia sem alteracao nenhuma (a **linha de
base**, que tem de estar verde), e depois aplica **uma** alteracao
deliberadamente errada de cada vez e exige que as suites falhem.

As mutacoes sao sobre o que o ticket chama isolamento e recusa: a forma da
chave, o dono da chave, o prefixo de listagem, a segunda camada da listagem, o
tecto do TTL, a expiracao e a adulteracao de URLs, o destino sem `apd_ref`, e o
que uma mensagem de erro nao pode dizer. Ha uma lista por linguagem, e cada
mutacao Python tem a sua gemea em TypeScript — as duas implementacoes sao
espelho uma da outra, e uma regra provada so de um lado e meia prova.

O filtro e um excerto do nome (`py:`, `ts:`, `prefixo`, `ttl`). `--aplicaveis`
confirma, em segundos e sem correr teste nenhum, que o texto de **todas** as
mutacoes ainda existe exactamente uma vez no ficheiro alvo: uma mutacao que
deixou de se aplicar e uma prova que deixou de provar, e conta como falha.

As suites TypeScript correm com o `node` da maquina, ou — se nao houver — num
contentor Node (o dos servicos, por digest), todas as mutacoes numa so execucao.

Nao faz parte de nenhum *gate*. Corre-se quando se mexe em `storage/` ou nos
seus testes, e o resultado regista-se no bloco do ticket e em
`docs/analises/ANALISE-09-KAM-011-storage-provider.md`. Uma mutacao que
**sobreviva** e um teste em falta.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
#: Fixada por digest e declarada em `ci/supply-chain/imagens.yaml` (KAM-067).
IMAGEM_NODE = (
    "node:24.21.0-trixie-slim"
    "@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66"
)

PY = "libs/py-core/src/kamba_core/storage"
TS = "packages/core-ts/src/storage"

#: As mutacoes que tiram a verificacao do dono a uma operacao mantem as outras
#: duas (contexto e forma), para que o que as apanha seja o teste de isolamento
#: e nao um `NameError`. Para isso precisam de mais dois nomes importados.
IMPORTA_PY = "from .chave import chave_do_ctx, prefixo_do_ctx, validar_classe\n"
IMPORTA_PY_MUTADO = (
    "from .chave import chave_do_ctx, partes_da_chave, prefixo_do_ctx, tenant_do_ctx, validar_classe\n"
)
IMPORTA_TS = 'import { chaveDoCtx, prefixoDoCtx, validarClasse } from "./chave.ts";\n'
IMPORTA_TS_MUTADO = (
    'import { chaveDoCtx, partesDaChave, prefixoDoCtx, tenantDoCtx, validarClasse } from "./chave.ts";\n'
)

#: (nome, ficheiro, texto original, texto mutado[, edicoes adicionais no mesmo ficheiro])
MUTACOES_PY = [
    ("dono: a chave de outro tenant passa", f"{PY}/chave.py",
     "    if partes.tenant_id != tenant:\n", "    if False:\n"),
    ("forma: lixo depois da chave passa (match em vez de fullmatch)", f"{PY}/chave.py",
     "    m = _CHAVE.fullmatch(key)", "    m = _CHAVE.match(key)"),
    ("forma: o mes aceita 00 e 13", f"{PY}/chave.py",
     "/(0[1-9]|1[0-2])/", "/([0-9]{{2}})/"),
    ("forma: a classe aceita barras", f"{PY}/chave.py",
     '_CLASSE = r"[a-z][a-z0-9_]{1,31}"', '_CLASSE = r"[a-z][a-z0-9_/]{1,31}"'),
    ("forma: a classe aceita maiusculas", f"{PY}/chave.py",
     '_CLASSE = r"[a-z][a-z0-9_]{1,31}"', '_CLASSE = r"[A-Za-z][A-Za-z0-9_]{1,31}"'),
    ("contexto: tenant em maiusculas aceite", f"{PY}/chave.py",
     "_UUID_CANONICO = re.compile(_UUID)", "_UUID_CANONICO = re.compile(_UUID, re.IGNORECASE)"),
    ("contexto: lixo depois do tenant passa", f"{PY}/chave.py",
     "_UUID_CANONICO.fullmatch(tenant) is None", "_UUID_CANONICO.match(tenant) is None"),
    ("contexto: tenant vazio nao e falta de contexto", f"{PY}/chave.py",
     '    if tenant is None or tenant == "":\n', "    if tenant is None:\n"),
    ("prefixo: o de outro tenant passa", f"{PY}/chave.py",
     "    if not prefix.startswith(base):\n", "    if False:\n"),
    ("prefixo: sem a barra final", f"{PY}/chave.py",
     '    return f"t/{tenant_do_ctx(ctx)}/"', '    return f"t/{tenant_do_ctx(ctx)}"'),
    ("prefixo: caracteres fora do alfabeto passam", f"{PY}/chave.py",
     "        or _RESTO_DE_PREFIXO.fullmatch(resto) is None\n", ""),
    ("prefixo: segmentos vazios passam", f"{PY}/chave.py",
     '        or "//" in resto\n', ""),
    ("prefixo: comprimento sem tecto", f"{PY}/chave.py",
     "        len(prefix) > _COMPRIMENTO_MAXIMO\n", "        False\n"),
    ("guarda: get sem conferir o dono", f"{PY}/guarda.py",
     '        chave_do_ctx(ctx, key, "get")\n',
     "        tenant_do_ctx(ctx)\n        partes_da_chave(key)\n",
     [(IMPORTA_PY, IMPORTA_PY_MUTADO)]),
    ("guarda: delete sem conferir o dono", f"{PY}/guarda.py",
     '        chave_do_ctx(ctx, key, "delete")\n',
     "        tenant_do_ctx(ctx)\n        partes_da_chave(key)\n",
     [(IMPORTA_PY, IMPORTA_PY_MUTADO)]),
    ("guarda: sign_url sem conferir o dono", f"{PY}/guarda.py",
     '        chave_do_ctx(ctx, key, "sign_url")\n',
     "        tenant_do_ctx(ctx)\n        partes_da_chave(key)\n",
     [(IMPORTA_PY, IMPORTA_PY_MUTADO)]),
    ("guarda: head sem conferir o dono", f"{PY}/guarda.py",
     '        partes = chave_do_ctx(ctx, key, "head")\n',
     "        tenant_do_ctx(ctx)\n        partes = partes_da_chave(key)\n",
     [(IMPORTA_PY, IMPORTA_PY_MUTADO)]),
    ("guarda: put sem conferir o dono", f"{PY}/guarda.py",
     '        partes = chave_do_ctx(ctx, key, "put")\n',
     "        tenant_do_ctx(ctx)\n        partes = partes_da_chave(key)\n",
     [(IMPORTA_PY, IMPORTA_PY_MUTADO)]),
    ("guarda: a listagem nao confere o que o motor devolve", f"{PY}/guarda.py",
     "            if type(item.chave) is not str or not item.chave.startswith(prefixo):\n",
     "            if False:\n"),
    ("guarda: a listagem confere o tenant mas nao o prefixo pedido", f"{PY}/guarda.py",
     "not item.chave.startswith(prefixo):\n", "not item.chave.startswith(prefixo[:39]):\n"),
    ("guarda: a listagem corta em silencio", f"{PY}/guarda.py",
     "        if listagem.truncada or len(refs) > limite:\n", "        if False:\n"),
    ("guarda: limite de listagem sem tecto", f"{PY}/guarda.py",
     "            or limite > LIMITE_MAXIMO_DE_LISTAGEM\n", ""),
    ("ttl: tecto de 300 s retirado", f"{PY}/guarda.py",
     "            or ttl_seconds > TTL_MAXIMO_S\n", ""),
    ("ttl: tecto passa a 301 s", f"{PY}/port.py",
     "TTL_MAXIMO_S = 300", "TTL_MAXIMO_S = 301"),
    ("ttl: zero aceite", f"{PY}/guarda.py",
     "            or ttl_seconds < 1\n", "            or ttl_seconds < 0\n"),
    ("ttl: bool e subclasses de int aceites (isinstance)", f"{PY}/guarda.py",
     "            type(ttl_seconds) is not int\n", "            not isinstance(ttl_seconds, int)\n"),
    ("meta: classe diferente da da chave passa", f"{PY}/guarda.py",
     "        if classe != partes.classe:\n            raise MetaInvalidaError(",
     "        if False:\n            raise MetaInvalidaError("),
    ("meta: retain_until sem fuso passa", f"{PY}/guarda.py",
     "        if not isinstance(prazo, datetime) or prazo.tzinfo is None:\n",
     "        if not isinstance(prazo, datetime):\n"),
    ("meta: content_type com mudanca de linha passa", f"{PY}/guarda.py",
     "            or _TIPO_DE_CONTEUDO.fullmatch(meta.content_type) is None\n",
     "            or _TIPO_DE_CONTEUDO.match(meta.content_type) is None\n"),
    ("meta: head aceita a classe que vier", f"{PY}/guarda.py",
     "        if classe != partes.classe:\n            raise RespostaDoMotorInvalidaError(",
     "        if False:\n            raise RespostaDoMotorInvalidaError("),
    ("meta: retain_until guardado na hora local", f"{PY}/guarda.py",
     "    em_utc = instante.astimezone(UTC)\n", "    em_utc = instante\n"),
    ("fake: a URL nao expira", f"{PY}/fake.py",
     "        if int(self._agora().timestamp()) >= expira:\n", "        if False:\n"),
    ("fake: a URL expira um segundo tarde", f"{PY}/fake.py",
     "        if int(self._agora().timestamp()) >= expira:\n",
     "        if int(self._agora().timestamp()) > expira:\n"),
    ("fake: a assinatura da URL nao e conferida", f"{PY}/fake.py",
     "        if not hmac.compare_digest(\n", "        if False and not hmac.compare_digest(\n"),
    ("fake: a assinatura nao cobre a chave", f"{PY}/fake.py",
     'f"{chave}\\n{expira}".encode()', 'f"{expira}".encode()'),
    ("s3: a URL assinada ignora o TTL pedido", f"{PY}/sigv4.py",
     '("X-Amz-Expires", str(expira_s)),', '("X-Amz-Expires", "300"),'),
    ("s3: a assinatura nao cobre o caminho", f"{PY}/sigv4.py",
     '            caminho_canonico(partes.path or "/"),\n', '            "/",\n'),
    ("s3: os metadados ficam fora da assinatura", f"{PY}/sigv4.py",
     "        cabecalhos=finais,\n        hash_do_corpo=hash_do_corpo,",
     "        cabecalhos={n: v for n, v in finais.items() if not n.startswith('x-amz-meta-')},\n"
     "        hash_do_corpo=hash_do_corpo,"),
    ("s3: bucket inexistente passa por objecto inexistente", f"{PY}/s3.py",
     ' and chave is not None and codigo != "NoSuchBucket":', " and chave is not None:"),
    ("s3: a causa de um erro de rede sobe com a URL", f"{PY}/s3.py",
     "        except Exception:  # noqa: BLE001, S110\n            pass\n",
     "        except Exception:  # noqa: BLE001\n"
     "            raise ArmazenamentoIndisponivelError(operacao, None, None) from None\n"),
    ("s3: entrada de listagem sem tamanho passa por vazia", f"{PY}/s3.py",
     "                    or tamanho_bruto is None\n"
     "                    or _DIGITOS.fullmatch(tamanho_bruto) is None\n",
     ""),
    ("s3: listagem truncada sem continuacao devolve o que tem", f"{PY}/s3.py",
     '                raise ArmazenamentoIndisponivelError("list", resposta.estado, "SemContinuacao")',
     "                return Listagem(tuple(itens), truncada=False)"),
    ("s3: envio em partes nao e abortado quando falha", f"{PY}/s3.py",
     "            if envio is not None:\n                # Um envio em partes abandonado",
     "            if False:\n                # Um envio em partes abandonado"),
    ("destino: prod arranca fora de AO sem apd_ref", f"{PY}/config.py",
     '        if ambiente == "prod":\n', "        if False:\n"),
    ("destino: so se exige apd_ref a um pais concreto", f"{PY}/config.py",
     "    if country != PAIS_SEM_TRANSFERENCIA and apd_ref is None:\n",
     '    if country == "US" and apd_ref is None:\n'),
    ("destino: country em falta vale AO", f"{PY}/config.py",
     '    country = exigir(VAR_COUNTRY, _PAIS, "ISO 3166-1 alfa-2, em maiusculas")\n',
     '    country = _ler(env, VAR_COUNTRY) or "AO"\n'),
    ("destino: provider em falta vale um nome qualquer", f"{PY}/config.py",
     '    provider = exigir(VAR_PROVIDER, _FORNECEDOR, "identificador em minusculas")\n',
     '    provider = _ler(env, VAR_PROVIDER) or "desconhecido"\n'),
    ("destino: uma apd_ref mal formada serve", f"{PY}/config.py",
     "    if apd_ref is not None and _APD_REF.fullmatch(apd_ref) is None:\n", "    if False:\n"),
    ("config: endpoint com credenciais embutidas passa", f"{PY}/config.py",
     r"""://([a-z0-9](?:""", r"""://((?:[a-z0-9:]+@)?[a-z0-9](?:"""),
    ("config: endpoint com caminho passa", f"{PY}/config.py",
     '(?::([0-9]{1,5}))?/?"\n', '(?::([0-9]{1,5}))?(?:/[a-z0-9./?#]*)?"\n'),
    ("config: porta 0 e porta acima de 65535 passam", f"{PY}/config.py",
     "        if m is None or (porta is not None and not 0 < porta < 65536):\n", "        if m is None:\n"),
    ("config: o strip() do Python volta a tirar caracteres de controlo", f"{PY}/config.py",
     '    valor = (env.get(nome) or "").strip(_BRANCOS)\n', '    valor = (env.get(nome) or "").strip()\n'),
    ("ambiente: um ambiente desconhecido arranca como se nao fosse prod", f"{PY}/config.py",
     "    if type(ambiente) is not str or ambiente not in AMBIENTES:\n", "    if False:\n"),
    ("ambiente: subclasse de str passa por ambiente", f"{PY}/config.py",
     "    if type(ambiente) is not str or ambiente not in AMBIENTES:\n",
     "    if not isinstance(ambiente, str) or ambiente not in AMBIENTES:\n"),
    ("tipos: subclasse de str passa por tenant", f"{PY}/chave.py",
     "    if type(tenant) is not str or _UUID_CANONICO.fullmatch(tenant) is None:\n",
     "    if not isinstance(tenant, str) or _UUID_CANONICO.fullmatch(tenant) is None:\n"),
    ("tipos: subclasse de str passa por chave", f"{PY}/chave.py",
     '    if type(key) is not str:\n', '    if not isinstance(key, str):\n'),
    ("tipos: subclasse de str passa por prefixo", f"{PY}/chave.py",
     "    if type(prefix) is not str:\n", "    if not isinstance(prefix, str):\n"),
    ("tipos: subclasse de str passa por classe", f"{PY}/chave.py",
     "    if type(classe) is not str or", "    if not isinstance(classe, str) or"),
    ("tipos: subclasse de int passa por limite", f"{PY}/guarda.py",
     "            type(limite) is not int\n", "            not isinstance(limite, int)\n"),
    ("tipos: chave listada que e subclasse de str passa", f"{PY}/guarda.py",
     "            if type(item.chave) is not str or", "            if not isinstance(item.chave, str) or"),
    # Duas mutacoes que existem do lado TypeScript **nao** tem gemea aqui, por
    # serem equivalentes em Python (sobreviveram na primeira passagem depois da
    # revisao, e nenhum teste as pode apanhar):
    #   - «instante sem ida e volta»: o `datetime.fromisoformat` ja recusa um 30
    #     de Fevereiro e uma hora 24, que o `Date` do JavaScript corrige em
    #     silencio. A ida e volta fica no codigo como segunda rede;
    #   - «assinatura do fake com lixo no fim»: a comparacao exacta que vem a
    #     seguir (`compare_digest`) recusa-a de qualquer modo.
    ("instante: put escreve um prazo que head nao le", f"{PY}/guarda.py",
     "        if ler_instante(prazo_texto) is None:\n", "        if False:\n"),
    ("corpo: blocos que nao sao bytes chegam ao motor", f"{PY}/guarda.py",
     "    return _so_bytes(body)\n", "    return body\n"),
    ("xml: ponto de codigo impossivel rebenta", f"{PY}/s3.py",
     "        except (ValueError, OverflowError):\n", "        except KeyError:\n"),
    ("s3: max-keys ignora o limite pedido", f"{PY}/s3.py",
     '                "max-keys": str(min(_PAGINA, maximo - len(itens))),\n',
     '                "max-keys": str(_PAGINA),\n'),
    ("s3: 404 numa listagem passa por objecto inexistente", f"{PY}/s3.py",
     ' and chave is not None and codigo != "NoSuchBucket":', ' and codigo != "NoSuchBucket":'),
    ("s3: valores de cabecalho sem normalizar espacos", f"{PY}/sigv4.py",
     '(nome.lower(), " ".join(valor.split()))', "(nome.lower(), valor)"),
    ("s3: parte por omissao de 32 MiB", f"{PY}/s3.py",
     "PARTE_POR_OMISSAO = 16 * 1024 * 1024", "PARTE_POR_OMISSAO = 32 * 1024 * 1024"),
    ("s3: TLS sem verificacao de certificado", f"{PY}/s3.py",
     "context=ssl.create_default_context(),", "context=ssl._create_unverified_context(),"),
    ("s3: sem tempo limite no transporte", f"{PY}/s3.py",
     '                partes.hostname or "", partes.port, timeout=tempo_limite_s\n',
     '                partes.hostname or "", partes.port\n'),
    ("s3: a query vai na rede com + em vez de %20", f"{PY}/s3.py",
     "urlencode(query, quote_via=quote, safe='-_.~')", "urlencode(query)"),
    ("erro: a chave recusada aparece na mensagem", f"{PY}/chave.py",
     '        raise ChaveInvalidaError(\n            "esperava t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}, em minusculas"\n        )',
     '        raise ChaveInvalidaError(f"esperava a forma canonica, veio {key}")'),
    ("erro: o tenant recusado aparece na mensagem", f"{PY}/chave.py",
     "        raise TenantInvalidoError(\n"
     "            type(tenant).__name__, len(tenant) if type(tenant) is str else 0\n        )",
     "        raise TenantInvalidoError(str(tenant), 0)"),
    ("segredos: credenciais lidas uma vez e guardadas", f"{PY}/config.py",
     "    def credenciais() -> Credenciais:\n        return Credenciais(\n"
     '            secrets.get("storage_access_key_id"),\n'
     '            secrets.get("storage_secret_access_key"),\n        )\n',
     "    _fixas = Credenciais(\n"
     '        secrets.get("storage_access_key_id"),\n'
     '        secrets.get("storage_secret_access_key"),\n    )\n\n'
     "    def credenciais() -> Credenciais:\n        return _fixas\n"),
]

MUTACOES_TS = [
    ("dono: a chave de outro tenant passa", f"{TS}/chave.ts",
     "  if (partes.tenantId !== tenant) {\n", "  if (false) {\n"),
    ("forma: lixo depois da chave passa (sem ancora final)", f"{TS}/chave.ts",
     "/(0[1-9]|1[0-2])/(${UUID})$`);", "/(0[1-9]|1[0-2])/(${UUID})`);"),
    ("forma: lixo antes da chave passa (sem ancora inicial)", f"{TS}/chave.ts",
     "const CHAVE = new RegExp(`^t/(", "const CHAVE = new RegExp(`t/("),
    ("forma: o mes aceita 00 e 13", f"{TS}/chave.ts",
     "/(0[1-9]|1[0-2])/", "/([0-9]{2})/"),
    ("forma: a classe aceita barras", f"{TS}/chave.ts",
     'const CLASSE = "[a-z][a-z0-9_]{1,31}";', 'const CLASSE = "[a-z][a-z0-9_/]{1,31}";'),
    ("forma: a classe aceita maiusculas", f"{TS}/chave.ts",
     'const CLASSE = "[a-z][a-z0-9_]{1,31}";', 'const CLASSE = "[A-Za-z][A-Za-z0-9_]{1,31}";'),
    ("contexto: tenant em maiusculas aceite", f"{TS}/chave.ts",
     "const UUID_CANONICO = new RegExp(`^${UUID}$`);", 'const UUID_CANONICO = new RegExp(`^${UUID}$`, "i");'),
    ("contexto: lixo depois do tenant passa", f"{TS}/chave.ts",
     "const UUID_CANONICO = new RegExp(`^${UUID}$`);", "const UUID_CANONICO = new RegExp(`^${UUID}`);"),
    ("contexto: tenant vazio nao e falta de contexto", f"{TS}/chave.ts",
     '  if (tenant === null || tenant === undefined || tenant === "") {\n',
     "  if (tenant === null || tenant === undefined) {\n"),
    ("prefixo: o de outro tenant passa", f"{TS}/chave.ts",
     "  if (!prefix.startsWith(base)) {\n", "  if (false) {\n"),
    ("prefixo: sem a barra final", f"{TS}/chave.ts",
     "  return `t/${tenantDoCtx(ctx)}/`;", "  return `t/${tenantDoCtx(ctx)}`;"),
    ("prefixo: caracteres fora do alfabeto passam", f"{TS}/chave.ts",
     "    !RESTO_DE_PREFIXO.test(resto) ||\n", ""),
    ("prefixo: segmentos vazios passam", f"{TS}/chave.ts",
     '    resto.includes("//") ||\n', ""),
    ("prefixo: comprimento sem tecto", f"{TS}/chave.ts",
     "    prefix.length > COMPRIMENTO_MAXIMO ||\n", ""),
    ("guarda: get sem conferir o dono", f"{TS}/guarda.ts",
     '    chaveDoCtx(ctx, key, "get");\n',
     "    tenantDoCtx(ctx);\n    partesDaChave(key);\n",
     [(IMPORTA_TS, IMPORTA_TS_MUTADO)]),
    ("guarda: delete sem conferir o dono", f"{TS}/guarda.ts",
     '    chaveDoCtx(ctx, key, "delete");\n',
     "    tenantDoCtx(ctx);\n    partesDaChave(key);\n",
     [(IMPORTA_TS, IMPORTA_TS_MUTADO)]),
    ("guarda: signUrl sem conferir o dono", f"{TS}/guarda.ts",
     '    chaveDoCtx(ctx, key, "signUrl");\n',
     "    tenantDoCtx(ctx);\n    partesDaChave(key);\n",
     [(IMPORTA_TS, IMPORTA_TS_MUTADO)]),
    ("guarda: head sem conferir o dono", f"{TS}/guarda.ts",
     '    const partes = chaveDoCtx(ctx, key, "head");\n',
     "    tenantDoCtx(ctx);\n    const partes = partesDaChave(key);\n",
     [(IMPORTA_TS, IMPORTA_TS_MUTADO)]),
    ("guarda: put sem conferir o dono", f"{TS}/guarda.ts",
     '    const partes = chaveDoCtx(ctx, key, "put");\n',
     "    tenantDoCtx(ctx);\n    const partes = partesDaChave(key);\n",
     [(IMPORTA_TS, IMPORTA_TS_MUTADO)]),
    ("guarda: a listagem nao confere o que o motor devolve", f"{TS}/guarda.ts",
     '      if (typeof item.chave !== "string" || !item.chave.startsWith(prefixo)) {\n',
     "      if (false) {\n"),
    ("guarda: a listagem confere o tenant mas nao o prefixo pedido", f"{TS}/guarda.ts",
     "!item.chave.startsWith(prefixo)) {\n", "!item.chave.startsWith(prefixo.slice(0, 39))) {\n"),
    ("guarda: a listagem corta em silencio", f"{TS}/guarda.ts",
     "    if (truncada || refs.length > limite) {\n", "    if (false) {\n"),
    ("guarda: limite de listagem sem tecto", f"{TS}/guarda.ts",
     "    if (!Number.isInteger(limite) || limite < 1 || limite > LIMITE_MAXIMO_DE_LISTAGEM) {\n",
     "    if (!Number.isInteger(limite) || limite < 1) {\n"),
    ("ttl: tecto de 300 s retirado", f"{TS}/guarda.ts",
     " || ttl < 1 || ttl > TTL_MAXIMO_S) {", " || ttl < 1) {"),
    ("ttl: tecto passa a 301 s", f"{TS}/port.ts",
     "export const TTL_MAXIMO_S = 300;", "export const TTL_MAXIMO_S = 301;"),
    ("ttl: zero aceite", f"{TS}/guarda.ts",
     " || ttl < 1 || ttl > TTL_MAXIMO_S) {", " || ttl < 0 || ttl > TTL_MAXIMO_S) {"),
    ("ttl: fraccoes aceites", f"{TS}/guarda.ts",
     '    if (typeof ttl !== "number" || !Number.isInteger(ttl) || ttl < 1',
     '    if (typeof ttl !== "number" || Number.isNaN(ttl) || ttl < 1'),
    ("meta: classe diferente da da chave passa", f"{TS}/guarda.ts",
     "    if (classe !== partes.classe) {\n      throw new MetaInvalidaError(",
     "    if (false) {\n      throw new MetaInvalidaError("),
    ("meta: retainUntil invalido passa", f"{TS}/guarda.ts",
     "    if (!(prazo instanceof Date) || Number.isNaN(prazo.getTime())) {\n",
     "    if (!(prazo instanceof Date)) {\n"),
    ("meta: contentType nao e validado", f"{TS}/guarda.ts",
     '    if (typeof meta.contentType !== "string" || !TIPO_DE_CONTEUDO.test(meta.contentType)) {\n',
     '    if (typeof meta.contentType !== "string") {\n'),
    ("meta: head aceita a classe que vier", f"{TS}/guarda.ts",
     "    if (classe !== partes.classe) {\n      throw new RespostaDoMotorInvalidaError(",
     "    if (false) {\n      throw new RespostaDoMotorInvalidaError("),
    ("instante: head aceita qualquer data que o Date leia", f"{TS}/guarda.ts",
     '  if (typeof texto !== "string" || !INSTANTE.test(texto)) return null;\n',
     '  if (typeof texto !== "string") return null;\n'),
    ("instante: data impossivel lida do servidor (sem ida e volta)", f"{TS}/guarda.ts",
     " || instante.toISOString() !== texto) return null;", ") return null;"),
    ("instante: put escreve um prazo que head nao le", f"{TS}/guarda.ts",
     "    if (lerInstante(prazoTexto) === null) {\n", "    if (false) {\n"),
    ("corpo: blocos que nao sao bytes chegam ao motor", f"{TS}/guarda.ts",
     "Symbol.asyncIterator in body) return soBytes(body);", "Symbol.asyncIterator in body) return body;"),
    ("fake: assinatura com lixo no fim aceite", f"{TS}/fake.ts",
     "&assinatura=([0-9a-f]{64})$/", "&assinatura=([0-9a-f]{64})/"),
    ("fake: expira fraccionado aceite", f"{TS}/fake.ts",
     "expira=([0-9]{1,12})&", "expira=([0-9.]{1,12})&"),
    ("xml: ponto de codigo impossivel rebenta", f"{TS}/s3.ts",
     "    return Number.isInteger(ponto) && ponto <= 0x10ffff ? String.fromCodePoint(ponto) : tudo;\n",
     "    return String.fromCodePoint(ponto);\n"),
    ("s3: max-keys ignora o limite pedido", f"{TS}/s3.ts",
     '        "max-keys": String(Math.min(PAGINA, maximo - itens.length)),\n',
     '        "max-keys": String(PAGINA),\n'),
    ("s3: 404 numa listagem passa por objecto inexistente", f"{TS}/s3.ts",
     ' && chave !== null && codigo !== "NoSuchBucket") {', ' && codigo !== "NoSuchBucket") {'),
    ("s3: valores de cabecalho sem normalizar espacos", f"{TS}/sigv4.ts",
     '[nome.toLowerCase(), valor.trim().replace(/\\s+/g, " ")] as const', "[nome.toLowerCase(), valor] as const"),
    ("s3: parte por omissao de 32 MiB", f"{TS}/s3.ts",
     "export const PARTE_POR_OMISSAO = 16 * 1024 * 1024;", "export const PARTE_POR_OMISSAO = 32 * 1024 * 1024;"),
    ("s3: sem tempo limite no transporte", f"{TS}/s3.ts",
     "      signal: AbortSignal.timeout(tempoLimiteMs),\n", ""),
    ("s3: a query vai na rede pelo URLSearchParams", f"{TS}/s3.ts",
     "`${codificar(nome)}=${codificar(valor)}`", "new URLSearchParams([[nome, valor]]).toString()"),
    ("chave: mes local em vez de UTC", f"{TS}/chave.ts",
     "  const mes = String(agora.getUTCMonth() + 1).padStart(2, \"0\");",
     "  const mes = String(agora.getMonth() + 1).padStart(2, \"0\");"),
    ("ambiente: um ambiente desconhecido arranca como se nao fosse prod", f"{TS}/config.ts",
     "  if (!isAmbiente(o.ambiente)) {\n", "  if (false) {\n"),
    ("config: porta 0 e porta acima de 65535 passam", f"{TS}/config.ts",
     "    if (m === null || (porta !== null && (porta < 1 || porta > 65535))) {\n", "    if (m === null) {\n"),
    ("config: o trim() do JavaScript volta a tirar o BOM", f"{TS}/config.ts",
     '  const valor = (env[nome] ?? "").replace(BRANCOS, "");\n', '  const valor = (env[nome] ?? "").trim();\n'),
    ("fake: a URL nao expira", f"{TS}/fake.ts",
     "    if (Math.floor(this.#agora().getTime() / 1000) >= expira) return recusado;\n", ""),
    ("fake: a URL expira um segundo tarde", f"{TS}/fake.ts",
     "    if (Math.floor(this.#agora().getTime() / 1000) >= expira) return recusado;\n",
     "    if (Math.floor(this.#agora().getTime() / 1000) > expira) return recusado;\n"),
    ("fake: a assinatura da URL nao e conferida", f"{TS}/fake.ts",
     "    if (recebida.length !== esperada.length || !timingSafeEqual(recebida, esperada)) {\n",
     "    if (false) {\n"),
    ("fake: a assinatura nao cobre a chave", f"{TS}/fake.ts",
     ".update(`${chave}\\n${expira}`)", ".update(`${expira}`)"),
    ("s3: a URL assinada ignora o TTL pedido", f"{TS}/sigv4.ts",
     '    ["X-Amz-Expires", String(o.expiraS)],', '    ["X-Amz-Expires", "300"],'),
    ("s3: a assinatura nao cobre o caminho", f"{TS}/sigv4.ts",
     "    caminhoCanonico(pedido.url.pathname),\n    queryCanonica(", '    "/",\n    queryCanonica('),
    ("s3: os metadados ficam fora da assinatura", f"{TS}/sigv4.ts",
     "    { metodo: o.metodo, url: o.url, cabecalhos, hashDoCorpo, regiao: o.regiao, quando },\n",
     "    {\n      metodo: o.metodo,\n      url: o.url,\n"
     "      cabecalhos: Object.fromEntries(\n"
     '        Object.entries(cabecalhos).filter(([n]) => !n.startsWith("x-amz-meta-")),\n'
     "      ),\n      hashDoCorpo,\n      regiao: o.regiao,\n      quando,\n    },\n"),
    ("s3: bucket inexistente passa por objecto inexistente", f"{TS}/s3.ts",
     ' && chave !== null && codigo !== "NoSuchBucket") {', " && chave !== null) {"),
    ("s3: a causa de um erro de rede sobe com a URL", f"{TS}/s3.ts",
     "    } catch {\n      // A causa não sobe: a mensagem de um erro de rede pode trazer a URL.\n"
     "      throw new ArmazenamentoIndisponivelError(operacao, null, null);\n",
     "    } catch (erro) {\n"
     "      throw Object.assign(new ArmazenamentoIndisponivelError(operacao, null, null), { cause: erro });\n"),
    ("s3: entrada de listagem sem tamanho passa por vazia", f"{TS}/s3.ts",
     "        if (chave === null || tamanhoBruto === null || !/^[0-9]+$/.test(tamanhoBruto)) {\n",
     "        if (chave === null) {\n"),
    ("s3: listagem truncada sem continuacao devolve o que tem", f"{TS}/s3.ts",
     '        throw new ArmazenamentoIndisponivelError("list", resposta.estado, "SemContinuacao");',
     "        return { itens, truncada: false };"),
    ("s3: envio em partes nao e abortado quando falha", f"{TS}/s3.ts",
     "      if (upload !== null) {\n        // Um envio em partes abandonado",
     "      if (false) {\n        // Um envio em partes abandonado"),
    ("destino: prod arranca fora de AO sem apd_ref", f"{TS}/config.ts",
     '    if (o.ambiente === "prod") throw new DestinoSemApdRefError(country, provider);\n', ""),
    ("destino: so se exige apd_ref a um pais concreto", f"{TS}/config.ts",
     "  if (country !== PAIS_SEM_TRANSFERENCIA && apdRef === null) {\n",
     '  if (country === "US" && apdRef === null) {\n'),
    ("destino: country em falta vale AO", f"{TS}/config.ts",
     '  const country = exigir(VARIAVEIS.country, PAIS, "ISO 3166-1 alfa-2, em maiúsculas");\n',
     '  const country = ler(env, VARIAVEIS.country) ?? "AO";\n'),
    ("destino: provider em falta vale um nome qualquer", f"{TS}/config.ts",
     '  const provider = exigir(VARIAVEIS.provider, FORNECEDOR, "identificador em minúsculas");\n',
     '  const provider = ler(env, VARIAVEIS.provider) ?? "desconhecido";\n'),
    ("destino: uma apd_ref mal formada serve", f"{TS}/config.ts",
     "  if (apdRef !== null && !APD_REF.test(apdRef)) {\n", "  if (false) {\n"),
    ("config: endpoint com credenciais embutidas passa", f"{TS}/config.ts",
     r"""/^(https?):\/\/([a-z0-9](?:""", r"""/^(https?):\/\/((?:[a-z0-9:]+@)?[a-z0-9](?:"""),
    ("config: endpoint com caminho passa", f"{TS}/config.ts",
     r"""(?::([0-9]{1,5}))?\/?$/;""", r"""(?::([0-9]{1,5}))?(?:\/[a-z0-9.\/?#]*)?$/;"""),
    ("erro: a chave recusada aparece na mensagem", f"{TS}/chave.ts",
     '    throw new ChaveInvalidaError(\n      "esperava t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}, em minúsculas",\n    );',
     "    throw new ChaveInvalidaError(`esperava a forma canónica, veio ${key}`);"),
    ("erro: o tenant recusado aparece na mensagem", f"{TS}/chave.ts",
     '    throw new TenantInvalidoError(typeof tenant, typeof tenant === "string" ? tenant.length : 0);',
     "    throw new TenantInvalidoError(String(tenant), 0);"),
    ("segredos: credenciais lidas uma vez e guardadas", f"{TS}/config.ts",
     "      credenciais: async () => ({\n"
     '        accessKeyId: await secrets.get("storage_access_key_id"),\n'
     '        secretAccessKey: await secrets.get("storage_secret_access_key"),\n'
     "      }),\n",
     "      credenciais: (() => {\n"
     "        const fixas = (async () => ({\n"
     '          accessKeyId: await secrets.get("storage_access_key_id"),\n'
     '          secretAccessKey: await secrets.get("storage_secret_access_key"),\n'
     "        }))();\n        return () => fixas;\n      })(),\n"),
]



def _normalizar(lado: str, mutacao: tuple) -> tuple[str, str, list[tuple[str, str]]]:
    nome, ficheiro, original, mutado, *resto = mutacao
    return f"{lado}: {nome}", ficheiro, [(original, mutado), *(resto[0] if resto else [])]


#: (nome com o lado, ficheiro, lista de edicoes)
MUTACOES = [_normalizar("py", m) for m in MUTACOES_PY] + [_normalizar("ts", m) for m in MUTACOES_TS]

#: Tecto de uma execucao da suite Python. A suite leva segundos; acima disto
#: esta pendurada.
TEMPO_LIMITE_S = 300

#: O que se copia para fora do repositorio.
COPIAR = ("libs/py-core/src", "libs/py-core/tests", "packages/core-ts/src", "packages/core-ts/tests")

COMANDO_PY = ["-m", "unittest", "discover", "-s", "libs/py-core/tests", "-t", "libs/py-core/tests", "-p", "test_storage_*.py"]
SUITES_TS = "tests/storage.*.test.ts"


def aplicaveis() -> int:
    """Confirma que o texto de cada mutacao existe exactamente uma vez."""
    falhas = 0
    for nome, ficheiro, edicoes in MUTACOES:
        texto = (RAIZ / ficheiro).read_text(encoding="utf-8")
        for original, mutado in edicoes:
            vezes = texto.count(original)
            if vezes != 1:
                falhas += 1
                print(f"  NAO APLICAVEL  {nome}: o texto aparece {vezes} vez(es) em {ficheiro}")
                break
            if original == mutado:
                falhas += 1
                print(f"  SEM EFEITO     {nome}: a mutacao nao altera nada")
                break
    print(f"{len(MUTACOES) - falhas} de {len(MUTACOES)} mutacoes aplicaveis")
    return 1 if falhas else 0


def copiar(destino: Path) -> None:
    for relativo in COPIAR:
        shutil.copytree(
            RAIZ / relativo,
            destino / relativo,
            ignore=shutil.ignore_patterns("__pycache__", "integracao"),
        )


def correr_py(copia: Path) -> bool:
    """`True` se a suite Python passou na copia."""
    ambiente = {**os.environ, "PYTHONPATH": str(copia / "libs/py-core/src"), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        execucao = subprocess.run(
            [sys.executable, *COMANDO_PY],
            cwd=copia,
            env=ambiente,
            capture_output=True,
            check=False,
            timeout=TEMPO_LIMITE_S,
        )
    except subprocess.TimeoutExpired:
        # Uma suite que nao acaba nao passou. (Aconteceu: a mutacao que tira o
        # tempo limite ao transporte pendurava o teste que a devia apanhar.)
        return False
    return execucao.returncode == 0


def correr_ts(base: Path, nomes: list[str]) -> dict[str, bool]:
    """Corre a suite TypeScript em cada copia `base/<nome>`; `True` = passou."""
    if shutil.which("node"):
        saida = {}
        for nome in nomes:
            # O `node --test` nao expande *globs* por si em todas as plataformas.
            ficheiros = sorted(str(p) for p in (base / nome / "packages/core-ts/tests").glob("storage.*.test.ts"))
            saida[nome] = (
                subprocess.run(
                    ["node", "--test", *ficheiros],
                    cwd=base / nome / "packages/core-ts",
                    capture_output=True,
                    check=False,
                ).returncode
                == 0
            )
        return saida
    # Sem `node` na maquina: um contentor, todas as copias numa so execucao.
    guiao = (
        "for d in /mut/*/; do n=$(basename \"$d\"); cd \"$d/packages/core-ts\"; "
        f"if node --test {SUITES_TS} >/dev/null 2>&1; then echo \"$n passou\"; else echo \"$n falhou\"; fi; done"
    )
    execucao = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{base}:/mut:ro", IMAGEM_NODE, "sh", "-c", guiao],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "MSYS_NO_PATHCONV": "1"},
    )
    if execucao.returncode != 0:
        raise SystemExit(f"o contentor das suites TypeScript falhou:\n{execucao.stderr}")
    saida = {}
    for linha in execucao.stdout.splitlines():
        nome, _, estado = linha.partition(" ")
        saida[nome] = estado == "passou"
    return saida


def main() -> int:
    argumentos = sys.argv[1:]
    if "--aplicaveis" in argumentos:
        return aplicaveis()
    filtro = argumentos[0] if argumentos else ""
    escolhidas = [m for m in MUTACOES if filtro in m[0]]
    if not escolhidas:
        raise SystemExit(f"nenhuma mutacao tem {filtro!r} no nome")
    if aplicaveis() != 0:
        return 1

    with tempfile.TemporaryDirectory(prefix="kam011-mutacoes-") as temporario:
        base = Path(temporario)
        # Linha de base: a copia sem alteracao nenhuma tem de estar verde.
        copiar(base / "base")
        indices: dict[str, tuple[str, str]] = {}
        for i, (nome, ficheiro, edicoes) in enumerate(escolhidas):
            pasta = f"m{i:03d}"
            copiar(base / pasta)
            alvo = base / pasta / ficheiro
            texto = alvo.read_text(encoding="utf-8")
            for original, mutado in edicoes:
                texto = texto.replace(original, mutado)
            alvo.write_text(texto, encoding="utf-8", newline="\n")
            indices[pasta] = (nome, "py" if nome.startswith("py:") else "ts")

        ha_ts = any(lado == "ts" for _, lado in indices.values())
        print("==> linha de base", flush=True)
        base_py = correr_py(base / "base")
        pastas_ts = ["base", *[p for p, (_, lado) in indices.items() if lado == "ts"]] if ha_ts else []
        resultados_ts = correr_ts(base, pastas_ts) if ha_ts else {}
        print(f"    Python:     {'verde' if base_py else 'VERMELHA'}")
        if ha_ts:
            print(f"    TypeScript: {'verde' if resultados_ts.get('base') else 'VERMELHA'}")
        if not base_py or (ha_ts and not resultados_ts.get("base")):
            print("\nA linha de base nao esta verde: nenhuma mutacao prova nada.")
            return 1

        print(f"\n==> {len(escolhidas)} mutacoes", flush=True)
        sobreviventes = []
        for pasta, (nome, lado) in indices.items():
            passou = correr_py(base / pasta) if lado == "py" else resultados_ts.get(pasta, True)
            print(f"    {'SOBREVIVEU' if passou else 'apanhada  '}  {nome}", flush=True)
            if passou:
                sobreviventes.append(nome)

    print(f"\n{len(escolhidas) - len(sobreviventes)} de {len(escolhidas)} mutacoes apanhadas.")
    if sobreviventes:
        print("Sobreviventes (cada uma e um teste em falta):")
        for nome in sobreviventes:
            print(f"  - {nome}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
