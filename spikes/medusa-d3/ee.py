"""AC-7 — nenhum modulo ou *flag* Enterprise do Medusa activo.

    python spikes/medusa-d3/ee.py               # verifica a configuracao do spike
    python spikes/medusa-d3/ee.py --raiz <dir>  # verifica outra arvore

Corre **sem Docker, sem rede e sem base de dados**: le ficheiros. E de
proposito — o criterio pede «teste de CI verde», e um teste que precisa de
levantar o Medusa para dizer que o `medusa-config` nao tem `rbac` e um teste que
nao corre em todos os PR. Se a decisao D3 fechar na opcao B, isto e o que o
KAM-042 liga a um alvo `make ci-<n>`.

**O que esta CONFIRMADO** (`evidencia/E4` §2.1): o Medusa e MIT **excepto** os
materiais *Enterprise Edition* desde 2026-08-11 — RBAC (`rbac`, `policies`,
rotas `admin/rbac`) e SSO/OIDC (`providers/auth-oidc`); «activar qualquer
*feature flag* Enterprise constitui declaracao de que se detem acordo
comercial». O `docs/tecnica/03` §3.4 decide nao activar nenhuma.

Codigos de saida: 0 limpo, 1 encontrou material EE, 2 nao conseguiu verificar.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent

#: Os nomes que o `docs/tecnica/03` §3.4 e o `evidencia/E4` §2.1 nomeiam. Lista
#: fechada e **com a fonte ao lado**: um nome a mais aqui, inventado, fazia o
#: gate recusar configuracoes legitimas; um nome a menos deixava passar material
#: licenciado. Se a Medusa publicar outro modulo EE, acrescenta-se aqui com a
#: data e a fonte.
NOMES_EE = {
    "rbac": "RBAC (E4 §2.1; doc 03 §3.4)",
    "policies": "RBAC: `packages/core/framework/src/policies/` (E4 §2.1)",
    "auth-oidc": "SSO/OIDC: `providers/auth-oidc` (E4 §2.1)",
}

#: **O verdadeiro interruptor, e a lista do ticket nao o tem.**
#:
#: Medido em fonte primaria (2026-10-27, CONFIRMADO): o que liga o material EE
#: nao e um modulo no `medusa-config` — e uma *feature flag*, e a propria
#: licenca diz que liga-la e uma declaracao contratual («Enabling any Enterprise
#: feature flag constitutes a representation that you hold a valid commercial
#: agreement with MedusaJS, Inc.», `ENTERPRISE-LICENSE.md`).
#:
#: As duas flags, de `packages/medusa/src/feature-flags/`:
#:   rbac                -> MEDUSA_FF_RBAC                (default_val: false)
#:   rbac_filter_fields  -> MEDUSA_FF_RBAC_FILTER_FIELDS   (default_val: false)
#:
#: O AC-7 do KAM-041 nomeia `rbac`, `auth-oidc` e `policies`, e **nao nomeia**
#: `rbac_filter_fields` nem a forma `MEDUSA_FF_*`. Verifica-se aqui a lista
#: completa, e o relatorio devolve a lacuna a quem escreveu o criterio.
FLAGS_EE = {
    "rbac": "MEDUSA_FF_RBAC",
    "rbac_filter_fields": "MEDUSA_FF_RBAC_FILTER_FIELDS",
}

#: Pacotes npm de material EE.
#:
#: **Estar na arvore nao e estar activo, e a diferenca nao e um detalhe.**
#: Medido neste spike (2026-10-27, CONFIRMADO): o `@medusajs/medusa@2.21.2`
#: declara `@medusajs/rbac@2.21.2` e `@medusajs/auth-oidc@2.21.2` como
#: `dependencies` **directas**, ambas com `"license": "SEE LICENSE IN LICENSE"`.
#: Nao ha instalacao do Medusa v2.21.2 sem eles: `npm ci` traz-los sempre.
#:
#: Logo, um gate que falhasse por os encontrar em `node_modules` ou no fecho
#: falharia em **toda** a instalacao do Medusa e seria desligado na primeira
#: semana. O que o `evidencia/E4` §2.1 diz e «**activar** qualquer *feature
#: flag* Enterprise constitui declaracao de que se detem acordo comercial», e o
#: `docs/tecnica/03` §3.4 poe o controlo no sitio certo: «falha o *build* se
#: `medusa-config` contiver modulos ou flags EE».
#:
#: Este ficheiro aplica essa leitura:
#:   activacao no `medusa-config`            -> ACHADO (falha)
#:   dependencia **directa** nossa           -> ACHADO (falha): fomos nos
#:   presenca transitiva via @medusajs/medusa -> REGISTA-SE, nao falha
#: Medido (2026-10-27): `@medusajs/policies` **nao existe no npm** (HTTP 404) —
#: `policies` e um directorio dentro do `@medusajs/framework`, nao um pacote. Fica
#: fora desta lista; o nome continua em `NOMES_EE`, onde serve para apanhar uma
#: activacao por configuracao.
PACOTES_EE = (
    "@medusajs/rbac",
    "@medusajs/auth-oidc",
)

#: Quem, legitimamente, arrasta o material EE para a arvore. Se um pacote EE
#: aparecer sem ser por aqui, e preciso saber porque.
ARRASTA_LEGITIMAMENTE = "@medusajs/medusa"

#: Rotas que o E4 nomeia.
ROTAS_EE = ("admin/rbac",)

#: Ficheiros que se leem. Um ficheiro em falta e um achado, nao um salto: o
#: `medusa-config` e o sitio onde uma flag se activa, e nao o poder ler nao e o
#: mesmo que nao ter flags.
CONFIGURACOES = ("medusa-config.ts", "medusa-config.js", "package.json",
                 ".env", ".env.template")


class Achado:
    def __init__(self, ficheiro: str, linha: int, nome: str, razao: str) -> None:
        self.ficheiro, self.linha, self.nome, self.razao = ficheiro, linha, nome, razao

    def __str__(self) -> str:
        onde = f"{self.ficheiro}:{self.linha}" if self.linha else self.ficheiro
        return f"{onde}: {self.nome} — {self.razao}"


def verificar(projecto: Path) -> tuple[list[Achado], dict]:
    """Devolve `(achados, resumo)`. Resumo vai para o relatorio do spike."""
    achados: list[Achado] = []
    resumo: dict = {"projecto": str(projecto), "ficheiros_lidos": [],
                    "ficheiros_em_falta": [], "licenca": None, "versao": None}

    for nome in CONFIGURACOES:
        caminho = projecto / nome
        if not caminho.is_file():
            if nome == "medusa-config.js" and (projecto / "medusa-config.ts").is_file():
                continue  # um dos dois chega
            if nome == "medusa-config.ts" and (projecto / "medusa-config.js").is_file():
                continue
            # Um `.env` que nao existe nao e uma lacuna: as flags estao
            # `default_val: false` e o que nao esta escrito nao esta ligado.
            if nome in (".env", ".env.template"):
                continue
            resumo["ficheiros_em_falta"].append(nome)
            achados.append(Achado(
                nome, 0, "(ficheiro em falta)",
                "e onde uma flag Enterprise se activa; nao o poder ler nao e o "
                "mesmo que nao ter flags"))
            continue
        resumo["ficheiros_lidos"].append(nome)
        texto = caminho.read_text(encoding="utf-8")

        if nome == "package.json":
            # Uma dependencia **directa** nossa de um pacote EE e uma decisao
            # nossa, e essa falha. A presenca transitiva trata-se mais abaixo.
            manifesto = json.loads(texto)
            directas = {
                **(manifesto.get("dependencies") or {}),
                **(manifesto.get("devDependencies") or {}),
            }
            for pacote in PACOTES_EE:
                if pacote in directas:
                    achados.append(Achado(
                        nome, 0, pacote,
                        "declarado como dependencia **directa** deste projecto"))
            continue

        for numero, linha in enumerate(texto.split("\n"), start=1):
            limpa = linha.strip()
            # Um comentario que **nomeie** o modulo nao e uma activacao. Esta
            # linha existe porque o proprio cabecalho do `medusa-config.ts` do
            # spike explica que nao activa `rbac` — e um gate que lesse isso
            # como activacao era um gate que ninguem podia documentar.
            if limpa.startswith(("//", "*", "/*", "#")):
                continue
            for pacote in PACOTES_EE:
                if pacote in limpa:
                    achados.append(Achado(nome, numero, pacote,
                                          "pacote Enterprise (E4 §2.1)"))
            for rota in ROTAS_EE:
                if rota in limpa:
                    achados.append(Achado(nome, numero, rota,
                                          "rota Enterprise (E4 §2.1)"))
            # As *feature flags*, pela forma de ambiente e pela de configuracao.
            # `MEDUSA_FF_RBAC=false` nao e activacao; so o valor verdadeiro conta.
            for chave, variavel in FLAGS_EE.items():
                correspondencia = re.search(
                    rf"""{re.escape(variavel)}\s*[:=]\s*["']?(\w+)""", limpa)
                if correspondencia and correspondencia.group(1).lower() in (
                        "true", "1", "yes", "on"):
                    achados.append(Achado(
                        nome, numero, variavel,
                        f"*feature flag* Enterprise ligada (chave `{chave}`); "
                        "liga-la e, pelos termos da licenca, declarar acordo "
                        "comercial com a MedusaJS, Inc."))
                if re.search(
                        rf"""featureFlags\b[^\n]*["']?{re.escape(chave)}["']?\s*:\s*true""",
                        limpa):
                    achados.append(Achado(
                        nome, numero, chave,
                        "*feature flag* Enterprise ligada em `featureFlags`"))

            for chave, razao in NOMES_EE.items():
                # Procura-se a forma de activacao — `resolve: ".../rbac"`,
                # `"@medusajs/rbac"` — e nao a palavra solta.
                #
                # **`policies` nao entra pela forma `chave: true`.** `policies`
                # nao e um pacote (e um directorio do `@medusajs/framework`) e
                # `policies:` e um nome legitimo de chave em configuracoes de
                # CORS, de armazenamento e de retencao. Procurar `policies: {`
                # dava vermelho num gate **bloqueante** por causa de uma chave
                # que nada tem de Enterprise. Para `policies` valem so as formas
                # de pacote e de caminho; para `rbac`, a flag ja foi tratada no
                # bloco acima.
                formas = [
                    rf"""resolve\s*:\s*["'][^"']*{re.escape(chave)}""",
                    rf"""["']@medusajs/[^"']*{re.escape(chave)}["']""",
                ]
                if chave != "policies":
                    formas.append(
                        rf"""["']?{re.escape(chave)}["']?\s*:\s*(true|\{{)""")
                if any(re.search(forma, limpa) for forma in formas):
                    achados.append(Achado(nome, numero, chave, razao))

    # A arvore instalada, quando existe.
    modulos = projecto / "node_modules" / "@medusajs"
    resumo["node_modules_lido"] = modulos.is_dir()
    if modulos.is_dir():
        pacote_medusa = modulos / "medusa" / "package.json"
        if pacote_medusa.is_file():
            dados = json.loads(pacote_medusa.read_text(encoding="utf-8"))
            resumo["versao"] = dados.get("version")
            resumo["licenca"] = dados.get("license")

    # O fecho: onde a arvore inteira esta fixada, e onde se ve **quem** arrasta
    # cada pacote EE. E a diferenca entre «esta la porque o Medusa o traz» (que
    # se registra) e «esta la porque alguem o pos» (que falha).
    fecho = projecto / "package-lock.json"
    resumo["fecho_lido"] = fecho.is_file()
    resumo["ee_na_arvore"] = []
    if fecho.is_file():
        bloqueio = json.loads(fecho.read_text(encoding="utf-8"))
        pacotes = bloqueio.get("packages") or {}
        for pacote in PACOTES_EE:
            entrada = pacotes.get(f"node_modules/{pacote}")
            if entrada is None:
                continue
            arrastadores = sorted(
                (dono or "(raiz)").removeprefix("node_modules/")
                for dono, dados in pacotes.items()
                if pacote in (dados.get("dependencies") or {})
                or pacote in (dados.get("devDependencies") or {})
                or pacote in (dados.get("optionalDependencies") or {})
            )
            resumo["ee_na_arvore"].append({
                "pacote": pacote,
                "versao": entrada.get("version"),
                "licenca": entrada.get("license"),
                "arrastado_por": arrastadores,
            })
            de_fora = [d for d in arrastadores
                       if d not in (ARRASTA_LEGITIMAMENTE, "(raiz)")]
            if "(raiz)" in arrastadores:
                achados.append(Achado(
                    "package-lock.json", 0, pacote,
                    "no fecho como dependencia da raiz: fomos nos a pedi-lo"))
            elif not arrastadores:
                achados.append(Achado(
                    "package-lock.json", 0, pacote,
                    "no fecho e ninguem o declara: arvore inconsistente, e nao "
                    "se pode dizer que entrou por via legitima"))
            elif de_fora and ARRASTA_LEGITIMAMENTE not in arrastadores:
                achados.append(Achado(
                    "package-lock.json", 0, pacote,
                    f"arrastado por {de_fora}, e nao pelo "
                    f"`{ARRASTA_LEGITIMAMENTE}`: via inesperada"))

    return achados, resumo


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="ee", description=__doc__.split("\n")[0])
    analisador.add_argument("--raiz", type=Path, default=AQUI / "medusa",
                            help="o projecto Medusa a verificar")
    argumentos = analisador.parse_args(argv)
    projecto: Path = argumentos.raiz.resolve()
    if not projecto.is_dir():
        print(f"AC-7: {projecto} nao existe. Nao se conseguiu verificar.",
              file=sys.stderr)
        return 2

    achados, resumo = verificar(projecto)
    print(f"AC-7: {projecto}")
    print(f"     ficheiros lidos: {', '.join(resumo['ficheiros_lidos']) or '(nenhum)'}")
    if resumo["versao"]:
        print(f"     @medusajs/medusa {resumo['versao']}, licenca "
              f"{resumo['licenca']!r}")
    if not resumo["node_modules_lido"]:
        print("     node_modules nao lido (arvore nao instalada nesta arvore de "
              "ficheiros; o `npm ci` do harness instala para um volume nomeado)")
    # O que esta na arvore sem estar activo. **Imprime-se sempre**: e o facto que
    # mais custa esquecer, porque um leitor que veja «AC-7 verde» sem isto fica
    # a pensar que nao ha codigo Enterprise na instalacao, e ha.
    for registo in resumo.get("ee_na_arvore") or []:
        print(f"     na arvore (nao activo): {registo['pacote']}@"
              f"{registo['versao']} [{registo['licenca']}] "
              f"arrastado por {', '.join(registo['arrastado_por']) or '(ninguem)'}")
    if resumo.get("ee_na_arvore"):
        print("     -> estar na arvore nao e estar activo: a licenca condiciona "
              "**activar** a flag, nao possuir o codigo (ENTERPRISE-LICENSE.md)")
    if achados:
        print(f"\n     {len(achados)} achado(s):")
        for achado in achados:
            print(f"       {achado}")
        return 1
    print("     nenhum modulo nem flag Enterprise (rbac, auth-oidc, policies)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
