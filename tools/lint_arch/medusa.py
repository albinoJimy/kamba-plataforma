"""O *lint* de arquitectura do Registo de comercio (KAM-042, criterios 3 e 4).

Dois criterios do bloco KAM-042 pedem a mesma coisa que o `docs/tecnica/03`
§3.1 e §3.4 pedem, e pedem-na como *gate*:

* criterio 3: «O `medusa-config` com `rbac`, `auth-oidc` ou `policies` reprova o
  CI (AC-7)»;
* criterio 4: «Lint de arquitectura: nenhum import do SDK do Medusa nem acesso a
  BD `medusa` fora de `services/com/`; a TLS so chama a API interna do COM com
  `tenant_id` em cabecalho».

Corre dentro do `lint_arch` e nao num *gate* proprio, pela mesma razao que o
`tool_schema`: o `lint_arch` ja corre no *gate* 2 e no 11, e um *job* novo
acrescenta um contexto exigido ao *ruleset* de `main` — que e alteracao de regra
de bloqueio e nao se decide aqui.

## Sem isto, a costura existe no desenho e nao no codigo

«O COM e um servico nosso que **encapsula** o Registo. Os agentes chamam a TLS,
a TLS chama a porta; ninguem fora do COM tem credenciais do Medusa»
(`docs/tecnica/03` §3.1). E uma afirmacao sobre o codigo, e so um *lint* a
mantem verdadeira: no dia em que um `import` do SDK aparecer no AGR, o PA-03-1
deixa de ser uma costura e passa a ser um paragrafo.

## Tres precisoes que sairam de ler as fontes, e nenhuma e detalhe

1. **O esquema do Medusa e o `public`, nao um esquema `medusa`.** O
   `spikes/medusa-d3/medusa/medusa-config.ts` di-lo: «O schema do Medusa fica em
   `public`; o da plataforma em `platform`. (...) sao dois esquemas na mesma
   base». Logo «acesso a BD `medusa`» e a **base** `kamba_medusa` — a que o
   `infra/compose/postgres/initdb/01-bases-e-extensoes.sql` cria — e nao um
   qualificador `medusa.` em SQL, que nao existe em sitio nenhum. Um *lint* que
   procurasse `medusa.` ficava verde para sempre sobre nada.

2. **A verificacao das *flags* salta comentarios, de proposito.** O
   `medusa-config.ts` do spike nomeia as duas *flags* EE num comentario para
   documentar o controlo, e o `spikes/medusa-d3/ee.py` salta linhas de
   comentario pela mesma razao. Um *lint* que falhasse por as encontrar
   proibia **documentar a regra**, que e o oposto do que ela serve.

3. **Cobre cinco *flags* e o criterio nomeia tres.** As outras duas sao as do
   `docs/tecnica/03` §3.4, correccao 3, medidas no KAM-041: o interruptor real
   sao `MEDUSA_FF_RBAC` e `MEDUSA_FF_RBAC_FILTER_FIELDS`, e «a segunda nao esta
   nomeada em nenhum criterio do KAM-041 nem nos criterios de saida do
   EPIC-04». Nao e um limiar novo: e a lacuna que aquela correccao ja devolveu a
   quem escreveu o criterio, implementada do lado que morde.

## A metade do criterio 4 que um *lint* nao consegue impor

«A TLS so chama a API interna do COM com `tenant_id` em cabecalho» e uma regra
sobre **quem chama**, e um *lint* sobre chamadores e um aviso: quem escrever o
cliente noutro ficheiro, com outro nome, passa. O que morde e o lado do
**chamado** — a rota que recusa um pedido sem o cabecalho —, e e isso que o
`_rotas_internas_do_com` verifica: nenhuma rota `/internal/*` no COM sem o
`x-kamba-tenant` nomeado no mesmo ficheiro.

**Hoje ve zero rotas**, porque a API interna do COM ainda nao existe
(`services/com/src/app.ts` so tem o `/healthz`). E uma **sentinela**: fica verde
sobre nada e dispara no dia em que a primeira rota nascer sem o cabecalho. A
metade do chamador fica por impor, e esta nomeada na verificacao dos criterios
do bloco em vez de ser dada por cumprida.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

__all__ = ["check"]

#: O prefixo dos pacotes do Medusa no npm.
SDK = "@medusajs/"

#: A base de dados do Registo (`infra/compose/postgres/initdb/`).
BASE_DO_REGISTO = "kamba_medusa"

#: O cabecalho que a API interna do COM exige, ao lado do `x-kamba-interno`.
#: Nome novo, *proposta* no dicionario §3.39 (KAM-042). A forma segue o
#: `x-kamba-hnd-bot` do §3.32: minusculas, porque os cabecalhos ASGI chegam em
#: minusculas e um `X-Kamba-Tenant` escrito no codigo nunca casava.
CABECALHO_TENANT = "x-kamba-tenant"

#: O unico sitio onde o SDK do Medusa pode ser importado.
DONO_DO_SDK = "services/com/"

#: As cinco *flags* e modulos Enterprise. Ver a precisao 3 do cabecalho.
FLAGS_EE = (
    "rbac",
    "auth-oidc",
    "policies",
    "MEDUSA_FF_RBAC",
    "MEDUSA_FF_RBAC_FILTER_FIELDS",
)

#: Caminhos dispensados, cada um com a razao. **Nao e mecanismo de dispensa
#: generico**: sao dois, e os dois sao superficies que nao sao aplicacao.
DISPENSAS: dict[str, str] = {
    "spikes/medusa-d3/": (
        "a arvore do spike KAM-041, onde o Medusa foi fixado e medido. Nao e "
        "codigo de aplicacao, nao e implantado, e e de la que vem a evidencia "
        "da D3. Um lint que a proibisse apagava a medicao"
    ),
    "infra/compose/postgres/initdb/": (
        "quem **cria** a base kamba_medusa. E a superficie do administrador da "
        "base e nao um componente a acede-la; sem esta dispensa, a regra "
        "proibia a existencia da base que ela protege"
    ),
    "tools/lint_arch/medusa.py": "este ficheiro, que nomeia as cadeias que procura",
    "tools/lint_arch/tests/": "os canarios, que tem de poder escrever o que o lint recusa",
}

#: Extensoes onde um import ou uma ligacao pode viver.
_CODIGO = (".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs", ".py", ".sql")

#: `import ... from "@medusajs/x"`, `import "@medusajs/x"`, `require("@medusajs/x")`
#: e `from "@medusajs/x"` em qualquer ordem de aspas. **Nao** apanha o nome do
#: pacote em prosa: um comentario que escreva `@medusajs/*` nao e um import, e
#: este ficheiro e o proprio exemplo disso.
_IMPORT_TS = re.compile(
    r"""(?:^|\n)\s*(?:import|export)\b[^\n;]*?from\s*["'](@medusajs/[^"']+)["']"""
    r"""|(?:^|\n)\s*import\s*["'](@medusajs/[^"']+)["']"""
    r"""|\brequire\s*\(\s*["'](@medusajs/[^"']+)["']\s*\)"""
    r"""|\bimport\s*\(\s*["'](@medusajs/[^"']+)["']\s*\)""",
    re.MULTILINE,
)

#: Uma rota `/internal/...` declarada num ficheiro. A forma segue a do
#: `services/agr`: a rota aparece como cadeia literal.
_ROTA_INTERNA = re.compile(r"""["'](/internal/[a-z0-9/_-]*)["']""")


def _ficheiros(root: Path) -> list[str]:
    """Os ficheiros do git, seguidos e novos. O mesmo que o `canon_lint` faz.

    Pelo git e nao por `os.walk`: as copias em `.claude/worktrees/*` sao
    repositorios inteiros e o `node_modules` tem milhares de ficheiros com
    `@medusajs` dentro, nenhum deles escrito aqui.
    """
    resultado = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    saida = resultado.stdout.decode("utf-8", errors="replace")
    return sorted({p for p in saida.split("\0") if p and (root / p).is_file()})


def _dispensado(caminho: str) -> bool:
    return any(caminho.startswith(prefixo) for prefixo in DISPENSAS)


def _ler(root: Path, caminho: str) -> str | None:
    try:
        return (root / caminho).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _branco(m: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def _sem_comentarios(fonte: str, caminho: str = "") -> str:
    """A fonte com os comentarios substituidos por espaco da mesma altura.

    Substitui em vez de remover para que os numeros de linha nao mudem: um
    achado numa linha errada manda quem o le ao sitio errado, e e assim que um
    *lint* perde a confianca de quem o corre. Ha um canario a medi-lo.

    **Por linguagem, e nao os tres de uma vez.** A primeira versao aplicava
    `#`, `//` e `/* */` a tudo, e o canario da base apanhou-a no primeiro
    minuto: um `//` dentro de `postgresql://host/kamba_medusa` abria um
    «comentario» que comia o resto da linha — e com ele o nome da base. O
    *lint* ficava verde sobre uma cadeia de ligacao, que e exactamente o que
    ele existe para apanhar. Dai o `(?<!:)` no `//` **e** a escolha por
    extensao: um `#` no meio de um `.ts` nao e comentario, e um `//` no meio de
    um `.py` nem isso.
    """
    extensao = caminho.rsplit(".", 1)[-1].lower() if "." in caminho else ""
    if extensao in ("py",):
        return re.sub(r"(?m)#[^\n]*", _branco, fonte)
    if extensao in ("sql",):
        sem_bloco = re.sub(r"/\*.*?\*/", _branco, fonte, flags=re.DOTALL)
        return re.sub(r"(?m)--[^\n]*", _branco, sem_bloco)
    if extensao in ("yaml", "yml"):
        return re.sub(r"(?m)#[^\n]*", _branco, fonte)
    # TypeScript, JavaScript e o resto do codigo com sintaxe de C.
    sem_bloco = re.sub(r"/\*.*?\*/", _branco, fonte, flags=re.DOTALL)
    return re.sub(r"(?<!:)//[^\n]*", _branco, sem_bloco)


def _linha_de(fonte: str, posicao: int) -> int:
    return fonte.count("\n", 0, posicao) + 1


def _imports_do_sdk(root: Path, ficheiros: list[str]) -> list[str]:
    """Criterio 4, primeira metade: o SDK so dentro de `services/com/`."""
    achados: list[str] = []
    for caminho in ficheiros:
        if caminho.startswith(DONO_DO_SDK) or _dispensado(caminho):
            continue
        if caminho.endswith("package.json"):
            achados.extend(_dependencia_do_sdk(root, caminho))
            continue
        if not caminho.endswith(_CODIGO):
            continue
        fonte = _ler(root, caminho)
        if fonte is None or SDK not in fonte:
            continue
        for achado in _IMPORT_TS.finditer(_sem_comentarios(fonte, caminho)):
            pacote = next(g for g in achado.groups() if g)
            achados.append(
                f"{caminho}:{_linha_de(fonte, achado.start())}: import do SDK do "
                f"Medusa (`{pacote}`) fora de `{DONO_DO_SDK}`.\n"
                "    O COM encapsula o Registo e ninguem fora dele lhe fala "
                "(`docs/tecnica/03` §3.1, PA-03-1, KAM-042 criterio 4).\n"
                "    Chama a porta `CommerceRegistry` pela API interna do COM."
            )
    return achados


def _dependencia_do_sdk(root: Path, caminho: str) -> list[str]:
    """Um `@medusajs/*` declarado num manifesto que nao e o do COM."""
    fonte = _ler(root, caminho)
    if fonte is None or SDK not in fonte:
        return []
    try:
        dados = json.loads(fonte)
    except json.JSONDecodeError as erro:
        return [f"{caminho}: nao se conseguiu ler como JSON: {erro}"]
    if not isinstance(dados, dict):
        return []
    achados: list[str] = []
    for campo in ("dependencies", "devDependencies", "optionalDependencies"):
        secao = dados.get(campo)
        if not isinstance(secao, dict):
            continue
        for nome in sorted(secao):
            if nome.startswith(SDK):
                achados.append(
                    f"{caminho}: `{campo}` declara `{nome}` fora de "
                    f"`{DONO_DO_SDK}`.\n"
                    "    Um pacote declarado e um pacote que alguem pode "
                    "importar sem o gate ver um import novo "
                    "(KAM-042 criterio 4)."
                )
    return achados


def _base_do_registo(root: Path, ficheiros: list[str]) -> list[str]:
    """Criterio 4, segunda metade: a base `kamba_medusa` so no COM.

    **Varre codigo, e nao os `.md` nem os `.yaml`**, e as duas exclusoes tem
    razoes diferentes:

    * um documento **descreve** a base e nao lhe acede — o `docs/tecnica/03`
      tem de poder nomea-la para explicar a regra, e o `db/migrations/README.md`
      para explicar porque o `bootstrap.py` nao lhe da `CONNECT`;
    * um `.yaml` ficou de fora por medicao, nao por comodidade. O
      `ci/canon-lint.yaml` nomeia a base na **razao de uma dispensa** — prosa
      sobre a regra, nao uma ligacao — e no `infra/compose/` uma cadeia de
      ligacao pertence ao servico do bloco que a contem: um `DATABASE_URL` para
      o `kamba_medusa` e legitimo sob o `com:` e nao o e sob o `agr:`, e um
      *lint* por linha nao sabe em que bloco esta. **Essa metade fica por
      impor** — e da revisao da implantacao — e esta nomeada aqui em vez de ser
      dada por cumprida.

    Os comentarios saltam-se, pela mesma razao das *flags*: a `0020` e o
    `db/tests_agr/test_checkpointer.py` explicam, em comentario, que o Medusa e
    uma **base** e nao um esquema, e que por isso o mecanismo e o `CONNECT` e
    nao o `USAGE`. Proibir essa frase era proibir documentar a regra.
    """
    achados: list[str] = []
    for caminho in ficheiros:
        if caminho.startswith(DONO_DO_SDK) or _dispensado(caminho):
            continue
        if not caminho.endswith(_CODIGO):
            continue
        fonte = _ler(root, caminho)
        if fonte is None or BASE_DO_REGISTO not in fonte:
            continue
        limpa = _sem_comentarios(fonte, caminho)
        for achado in re.finditer(re.escape(BASE_DO_REGISTO), limpa):
            achados.append(
                f"{caminho}:{_linha_de(fonte, achado.start())}: referencia a base "
                f"`{BASE_DO_REGISTO}` fora de `{DONO_DO_SDK}`.\n"
                "    Nenhum componente fora do COM tem credenciais nem ligacao "
                "ao Registo (`docs/tecnica/03` §3.1, KAM-042 criterio 4)."
            )
    return achados


def _flags_ee(root: Path, ficheiros: list[str]) -> list[str]:
    """Criterio 3: um `medusa-config` com material Enterprise reprova o CI."""
    achados: list[str] = []
    for caminho in ficheiros:
        nome = caminho.rsplit("/", 1)[-1]
        if not nome.startswith("medusa-config"):
            continue
        fonte = _ler(root, caminho)
        if fonte is None:
            continue
        # **Os comentarios saltam-se aqui tambem**, e o ficheiro do spike e a
        # razao: ele nomeia as duas flags para documentar o controlo. Ver a
        # precisao 2 do cabecalho.
        limpa = _sem_comentarios(fonte, caminho)
        for flag in FLAGS_EE:
            for achado in re.finditer(
                rf"(?:^|[^A-Za-z0-9_-]){re.escape(flag)}(?![A-Za-z0-9_-])", limpa
            ):
                achados.append(
                    f"{caminho}:{_linha_de(fonte, achado.start())}: material "
                    f"Enterprise do Medusa (`{flag}`) no `medusa-config`.\n"
                    "    «Activar qualquer feature flag Enterprise constitui "
                    "declaracao de que se detem acordo comercial» "
                    "(`evidencia/E4` §2.1, CONFIRMADO).\n"
                    "    A decisao em vigor e nao activar (`docs/tecnica/03` "
                    "§3.4, ADR-003). Se passar a ser necessario, obtem-se "
                    "licenca escrita antes — nao se contorna."
                )
    return achados


def _rotas_internas_do_com(root: Path, ficheiros: list[str]) -> list[str]:
    """Criterio 4, terceira metade: a API interna do COM exige o tenant.

    **Sentinela.** Ver a ultima secao do cabecalho: hoje nao ha rotas
    `/internal/*` no COM, pelo que isto fica verde sobre nada — e dispara no dia
    em que a primeira nascer sem o cabecalho.
    """
    achados: list[str] = []
    for caminho in ficheiros:
        if not caminho.startswith(DONO_DO_SDK) or not caminho.endswith(_CODIGO):
            continue
        if "/tests/" in caminho:
            continue
        fonte = _ler(root, caminho)
        if fonte is None:
            continue
        limpa = _sem_comentarios(fonte, caminho)
        rotas = sorted({m.group(1) for m in _ROTA_INTERNA.finditer(limpa)})
        if not rotas:
            continue
        if CABECALHO_TENANT in limpa:
            continue
        achados.append(
            f"{caminho}: declara {len(rotas)} rota(s) interna(s) "
            f"({', '.join(rotas)}) e nao nomeia `{CABECALHO_TENANT}`.\n"
            "    O `ctx.tenantId` da porta vem do cabecalho e nunca do corpo "
            "nem do texto do cliente (KAM-042 criterio 1 e 4).\n"
            "    Ao lado do `x-kamba-interno` do dicionario §3.24, que prova "
            "«vem de dentro da rede» e nao «vem deste tenant»."
        )
    return achados


def check(root: Path) -> list[str]:
    """Os achados. Lista vazia e conforme."""
    try:
        ficheiros = _ficheiros(root)
    except (OSError, subprocess.CalledProcessError) as erro:
        raise OSError(f"nao foi possivel listar os ficheiros do git em {root}: {erro}")

    return [
        *_imports_do_sdk(root, ficheiros),
        *_base_do_registo(root, ficheiros),
        *_flags_ee(root, ficheiros),
        *_rotas_internas_do_com(root, ficheiros),
    ]
