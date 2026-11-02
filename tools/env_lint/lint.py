"""As regras do `env_lint` (KAM-075, gate 2).

Verifica quatro coisas que, antes deste ticket, so existiam em prosa:

  1. **A matriz bate com a configuracao.** `infra/ENVIRONMENTS.md` §2 e §7
     contra `infra/envs/*/env.yaml`, token a token (criterio 1).
  2. **`prod` nao passa a dados reais por distraccao.** `dados.classe: real`
     exige referencia de decisao D1 **e** pelo menos um `apd_ref` (criterio 4).
  3. **Um ambiente nao restaura copias de `prod`.** (criterio 3, teste negativo)
  4. **Um segredo de um ambiente nao e referenciado noutro.** (criterio 5)

E uma quinta, que e o que torna o criterio 6 medivel em vez de declarado:

  5. **Nenhum `.tf` fora de `infra/modules/provider-*/` declara um recurso.**

## O que este modulo NAO cobre, e tem de ser dito

* **Nao fala com fornecedor nenhum, nem com o cofre.** Le ficheiros. Que o
  projecto Doppler `staging` exista de facto e **NAO VERIFICADO** — nao ha conta
  (`docs/evidencia/KAM-010.md`). O que se verifica e o **mapeamento**, que e
  exactamente o que o criterio 5 pede deste ticket: «os projectos de segredos
  sao criados por KAM-010; este ticket so define o mapeamento e falha se o
  mapeamento for violado».
* **Nao mede tempo de provisionamento.** O criterio 2 (<= 30 min, mediana de 3
  execucoes) nao se verifica por leitura de ficheiros e **nao foi medido** —
  `infra/README.md` §5.
* **Nao le `services/`, `libs/`, `packages/` nem `ops/`.** O varrimento de
  referencias de segredo e sobre `infra/`, que e onde este ticket poe
  configuracao de ambiente. O uso de segredos em codigo tem o seu verificador,
  que e o `secrets_inventory` do KAM-010 (eixo `uso`).
* **Nao valida que o `apd_ref` existe na APD.** Valida a **forma**. Sao 0 de 14
  os destinos com protocolo (`GoLive_Gate.md` linha B2), e nenhuma leitura de
  ficheiro muda isso.

Codigo de saida: 0 limpo, 1 achados, 2 configuracao ilegivel. A distincao entre
1 e 2 importa como no `canon_lint`: uma matriz que nao se le nao pode parecer
uma matriz conforme.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from kamba_yaml import YamlSubsetError, exigir_chaves, load_file

# O inventario de segredos le-se pelo leitor do KAM-010 e **nao por um nosso**.
# Nao e comodidade: o `ops/secrets-inventory.yaml` usa listas em estilo de fluxo
# (`ambientes: [dev, staging, prod]`), que o `kamba_yaml` recusa de proposito —
# ele corre no `pre-commit` e um parser mais permissivo ali e risco que nao
# compensa (`tools/secrets_inventory/yamlsubset.py`, cabecalho). Reusar o leitor
# de quem e dono do ficheiro poupa um terceiro subconjunto de YAML neste
# repositorio, e poupa a divergencia entre dois.
from secrets_inventory.inventario import carregar as _carregar_inventario

from . import matriz

#: Os tres ambientes. O mesmo dominio que `tools/secrets_inventory` usa
#: (`inventario.py`): um quarto ambiente entra nos dois sitios ou em nenhum.
AMBIENTES = ("dev", "staging", "prod")

#: Os dois valores de `kamba_data_class`. O criterio 4 nomeia-os em ingles.
CLASSES_DE_DADOS = ("synthetic", "real")

#: O unico ambiente que pode ter segredos sem projecto remoto (doc 09 §6:
#: «Local, nao reutilizaveis»).
PROJECTO_LOCAL = "local"

#: Tecto do TTL do DNS. **Proposta** do bloco do KAM-075 (300 s), nao medicao:
#: a propagacao real mede-se no KAM-085. Fica como tecto e nao como igualdade
#: porque descer o TTL nunca piora o passo «DNS» do orcamento de RTO.
TTL_MAXIMO_PROPOSTO = 300

#: Forma de um `apd_ref`. **Nao e invencao deste ticket**: e a mesma expressao
#: que `libs/py-core/src/kamba_core/storage/config.py` e
#: `packages/core-ts/src/avisos/fornecedor.ts` ja usam (KAM-011).
APD_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$")

#: Forma de uma referencia de decisao D1. **Proposta deste ticket**, porque
#: nenhuma existia: os dois criterios que a exigem (`specs/EPIC-08` §1 e o
#: criterio 4 do KAM-075) escrevem «referencia de decisao D1» sem formato.
#: `D1/<data ISO>/<slug do que foi decidido>`, p. ex.
#: `D1/2026-12-01/jnb-cpt`. Entra em `specs/02` §3 como proposta.
DECISAO_D1 = re.compile(r"^D1/\d{4}-\d{2}-\d{2}/[a-z0-9][a-z0-9-]{0,63}$")

#: Onde vive o inventario de segredos do KAM-010. **Nao se duplica aqui**: os
#: `id` e os `ambientes` de cada segredo leem-se de la, para que um segredo novo
#: nao tenha de ser escrito em dois sitios que depois divergem.
CAMINHO_INVENTARIO = "ops/secrets-inventory.yaml"

CAMINHO_MATRIZ = "infra/ENVIRONMENTS.md"

#: Os dois segredos que o criterio 5 nomeia por extenso: «chaves Meta e do
#: facilitador **distintas** por ambiente». Os `id` sao os do inventario.
SEGREDOS_QUE_TEM_DE_SER_DISTINTOS = ("meta_app_secret", "proxypay_api_key")

#: Blocos de HCL que so podem existir atras da costura do fornecedor.
_BLOCO_DE_RECURSO = re.compile(r"^\s*(resource|data|provider)\s+\"", re.MULTILINE)

#: A costura. `fnmatchcase` e nao `fnmatch`: o segundo normaliza a caixa em
#: Windows e nao em Linux, e o mesmo repositorio dava respostas diferentes.
_PADRAO_DA_COSTURA = "infra/modules/provider-*/*"

#: Extensoes de **configuracao**, que sao as unicas onde se procuram referencias
#: de segredo.
#:
#: A FRONTEIRA E ENTRE CONFIGURACAO E DOCUMENTACAO, e nao e comodidade — foi
#: este lint a acusar o `infra/README.md` §4, que **documenta a forma** de uma
#: referencia e por isso tem de poder escrever `prod/META_APP_SECRET` como
#: exemplo. A primeira versao resolveu-o excluindo o nome de um ficheiro, que e
#: o inicio de uma lista de excepcoes; isto resolve a classe.
#:
#: O que se perde: uma referencia cruzada escrita em Markdown passa. E o certo:
#: o OpenTofu nao le `.md`, pelo que uma referencia ali **nao muda
#: comportamento nenhum**. Um *valor* de segredo em Markdown e outra coisa, e
#: quem responde por ele e o gate 9 (`scan_secrets`), que varre a arvore toda.
EXTENSOES_DE_CONFIGURACAO = (".tf", ".tftpl", ".hcl", ".yaml", ".yml", ".sh", ".json", ".env")

_CHAVES_DE_TOPO = {
    "versao",
    "ambiente",
    "dados",
    "compute",
    "meta",
    "facilitador",
    "llm",
    "segredos",
    "acesso",
    "dns",
    "custo",
}
_CHAVES = {
    "dados": {"classe", "decisao_d1", "apd_refs", "restauro_de"},
    "compute": {"forma", "vcpu", "memoria_gb", "disco"},
    "meta": {"modo", "assina_corpo"},
    "facilitador": {"modo", "proxypay_base", "sandbox_appypay"},
    "llm": {"modo", "budget"},
    "segredos": {"projecto", "cofre"},
    "acesso": {"modo"},
    "dns": {"ttl_segundos"},
    "custo": {"etiquetas", "mensal_usd"},
}

#: As sete chaves que o criterio 1 nomeia, na ordem do doc 09 §6.
CHAVES_DA_MATRIZ = (
    "dados.classe",
    "compute.forma",
    "meta.modo",
    "facilitador.modo",
    "llm.modo",
    "segredos.projecto",
    "acesso.modo",
)

#: As chaves da §7 — as que este ticket acrescenta a matriz.
CHAVES_ACRESCENTADAS = (
    "dns.ttl_segundos",
    "custo.etiquetas.kamba_env",
    "custo.etiquetas.kamba_data_class",
    "custo.mensal_usd",
    "dados.restauro_de",
)


class ConfiguracaoInvalida(ValueError):
    """Nao se consegue ler o que e preciso para verificar. Codigo de saida 2."""


@dataclass(frozen=True)
class Achado:
    codigo: str
    onde: str
    mensagem: str

    def __str__(self) -> str:
        return f"{self.codigo}: {self.onde}: {self.mensagem}"


@dataclass
class Dados:
    """Tudo o que as regras precisam, ja lido. As regras nao tocam no disco."""

    #: `ambiente` -> o mapa cru do `env.yaml`.
    ambientes: dict[str, dict] = field(default_factory=dict)
    linhas_da_matriz: list[matriz.Linha] = field(default_factory=list)
    linhas_acrescentadas: list[matriz.Linha] = field(default_factory=list)
    #: `id` do segredo -> ambientes em que existe (do inventario do KAM-010).
    inventario: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: `caminho relativo` -> texto, para os ficheiros de `infra/`.
    ficheiros: dict[str, str] = field(default_factory=dict)


# --- Leitura -----------------------------------------------------------------


def _ficheiros_do_git(raiz: Path, prefixo: str) -> list[str]:
    """Os ficheiros que o git segue **e** os novos ainda por seguir.

    Os nao seguidos entram para que o lint corrido antes do `git add` veja o que
    se acabou de escrever — e a mesma razao do `canon_lint`. No CI nao ha
    diferenca, porque a arvore esta limpa.
    """
    try:
        resultado = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", prefixo],
            cwd=raiz,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as excepcao:
        raise ConfiguracaoInvalida(
            f"nao foi possivel listar os ficheiros de {prefixo} em {raiz}: {excepcao}"
        ) from excepcao
    caminhos = [
        bruto
        for bruto in resultado.stdout.decode("utf-8", errors="replace").split("\0")
        if bruto and (raiz / bruto).is_file()
    ]
    return sorted(set(caminhos))


def _ler_inventario(raiz: Path) -> dict[str, tuple[str, ...]]:
    """`id` do segredo -> ambientes em que existe, do inventario do KAM-010.

    Os erros de **esquema** do inventario nao se repetem aqui: quem responde por
    eles e o `secrets_inventory`, que tem tres eixos e falha fechado. O que se
    recusa e o caso em que nao sobra nada para ler — porque um verificador que
    corre sobre populacao vazia passa sempre, e isso nao se distingue de verde.
    """
    try:
        inventario, _erros_do_esquema = _carregar_inventario(raiz)
    except Exception as excepcao:  # noqa: BLE001 — o leitor do KAM-010 tem a sua taxonomia
        raise ConfiguracaoInvalida(f"{CAMINHO_INVENTARIO}: {excepcao}") from excepcao
    lido = {segredo.id: tuple(segredo.ambientes) for segredo in inventario.segredos}
    if not lido:
        raise ConfiguracaoInvalida(
            f"{CAMINHO_INVENTARIO}: nenhum segredo lido. Corre "
            "`python -m secrets_inventory --root .. all` para ver porque"
        )
    return lido


def carregar(raiz: Path) -> Dados:
    """Le a matriz, os tres `env.yaml`, o inventario e os ficheiros de `infra/`.

    Uma leitura que falha levanta `ConfiguracaoInvalida` — nunca devolve um
    `Dados` meio vazio, porque um verificador que corre sobre populacao vazia
    passa sempre.
    """
    caminho_matriz = raiz / CAMINHO_MATRIZ
    if not caminho_matriz.is_file():
        raise ConfiguracaoInvalida(f"matriz ausente: {CAMINHO_MATRIZ}")
    texto_matriz = caminho_matriz.read_text(encoding="utf-8")
    try:
        linhas = matriz.ler(texto_matriz)
        acrescentadas = matriz.tabela_acrescentada(texto_matriz)
    except matriz.MatrizIlegivel as excepcao:
        raise ConfiguracaoInvalida(str(excepcao)) from excepcao

    ambientes: dict[str, dict] = {}
    for ambiente in AMBIENTES:
        caminho = raiz / "infra" / "envs" / ambiente / "env.yaml"
        if not caminho.is_file():
            continue
        try:
            ambientes[ambiente] = load_file(caminho)
        except YamlSubsetError as excepcao:
            raise ConfiguracaoInvalida(str(excepcao)) from excepcao

    ficheiros: dict[str, str] = {}
    for relativo in _ficheiros_do_git(raiz, "infra"):
        try:
            ficheiros[relativo] = (raiz / relativo).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Binario ou ilegivel: nao e texto, nao leva referencia de segredo.
            continue
    if not ficheiros:
        raise ConfiguracaoInvalida("nenhum ficheiro legivel em infra/ — o varrimento seria vazio")

    return Dados(
        ambientes=ambientes,
        linhas_da_matriz=linhas,
        linhas_acrescentadas=acrescentadas,
        inventario=_ler_inventario(raiz),
        ficheiros=ficheiros,
    )


# --- Normalizacao ------------------------------------------------------------


def _resolver(mapa: dict, chave: str):
    """Resolve `a.b.c` num mapa aninhado. `KeyError` se nao existir."""
    actual = mapa
    for parte in chave.split("."):
        if not isinstance(actual, dict) or parte not in actual:
            raise KeyError(chave)
        actual = actual[parte]
    return actual


def normalizar(valor) -> str:
    """O valor do YAML na forma em que a matriz o escreve.

    Deliberadamente total: tudo tem uma representacao, para que a comparacao
    nunca falhe por tipo e passe a falhar por conteudo, que e o que interessa.
    """
    if valor is None:
        return "null"
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, list):
        return "[]" if not valor else ", ".join(normalizar(item) for item in valor)
    return str(valor)


# --- Regras ------------------------------------------------------------------


def _regra_ambientes_existem(dados: Dados) -> list[Achado]:
    return [
        Achado(
            "ambiente-em-falta",
            f"infra/envs/{ambiente}/env.yaml",
            "o ficheiro nao existe; a estrutura `infra/envs/{dev,staging,prod}` "
            "e dos Detalhes Tecnicos do KAM-075",
        )
        for ambiente in AMBIENTES
        if ambiente not in dados.ambientes
    ]


def _regra_esquema(dados: Dados) -> list[Achado]:
    achados = []
    for ambiente, bruto in dados.ambientes.items():
        onde = f"infra/envs/{ambiente}/env.yaml"
        try:
            exigir_chaves(bruto, _CHAVES_DE_TOPO, onde)
            for secao, permitidas in _CHAVES.items():
                if secao in bruto:
                    exigir_chaves(bruto[secao], permitidas, f"{onde}:{secao}")
        except YamlSubsetError as excepcao:
            achados.append(Achado("chave-desconhecida", onde, str(excepcao)))
            continue
        declarado = bruto.get("ambiente")
        if declarado != ambiente:
            achados.append(
                Achado(
                    "ambiente-mal-declarado",
                    onde,
                    f"`ambiente: {declarado!r}` dentro da pasta {ambiente!r}",
                )
            )
    return achados


def _comparar_tabela(
    dados: Dados, linhas: list[matriz.Linha], esperadas: tuple[str, ...], secao: str
) -> list[Achado]:
    achados = []
    por_chave = {linha.chave: linha for linha in linhas}
    for chave in esperadas:
        if chave not in por_chave:
            achados.append(
                Achado(
                    "matriz-linha-em-falta",
                    f"{CAMINHO_MATRIZ} {secao}",
                    f"a chave `{chave}` nao tem linha na matriz",
                )
            )
            continue
        linha = por_chave[chave]
        for ambiente, bruto in sorted(dados.ambientes.items()):
            try:
                valor = normalizar(_resolver(bruto, chave))
            except KeyError:
                achados.append(
                    Achado(
                        "configuracao-sem-a-chave",
                        f"infra/envs/{ambiente}/env.yaml",
                        f"a matriz tem a linha `{chave}` e a configuracao nao tem a chave",
                    )
                )
                continue
            esperado = linha.valores[ambiente]
            if valor != esperado:
                achados.append(
                    Achado(
                        "matriz-divergente",
                        f"{CAMINHO_MATRIZ} {secao} / infra/envs/{ambiente}/env.yaml",
                        f"`{chave}`: a matriz diz {esperado!r} e a configuracao diz {valor!r}",
                    )
                )
    sobra = sorted(set(por_chave) - set(esperadas))
    for chave in sobra:
        achados.append(
            Achado(
                "matriz-linha-a-mais",
                f"{CAMINHO_MATRIZ} {secao}",
                f"a linha `{chave}` nao esta no conjunto verificado; "
                "uma linha nova entra tambem em CHAVES_DA_MATRIZ ou CHAVES_ACRESCENTADAS",
            )
        )
    return achados


def _regra_matriz(dados: Dados) -> list[Achado]:
    return _comparar_tabela(
        dados, dados.linhas_da_matriz, CHAVES_DA_MATRIZ, "§2"
    ) + _comparar_tabela(dados, dados.linhas_acrescentadas, CHAVES_ACRESCENTADAS, "§7")


def _regra_classe_de_dados(dados: Dados) -> list[Achado]:
    """O criterio 4: `real` so com referencia de D1 e com `apd_ref`."""
    achados = []
    for ambiente, bruto in sorted(dados.ambientes.items()):
        onde = f"infra/envs/{ambiente}/env.yaml"
        secao = bruto.get("dados")
        if not isinstance(secao, dict):
            achados.append(Achado("dados-ausente", onde, "falta a seccao `dados`"))
            continue
        classe = secao.get("classe")
        if classe not in CLASSES_DE_DADOS:
            achados.append(
                Achado(
                    "classe-desconhecida",
                    onde,
                    f"`dados.classe` e {classe!r}; os valores sao {CLASSES_DE_DADOS}",
                )
            )
            continue

        decisao = secao.get("decisao_d1")
        refs = secao.get("apd_refs") if isinstance(secao.get("apd_refs"), list) else []

        if classe == "real":
            if not isinstance(decisao, str) or decisao.strip() == "":
                achados.append(
                    Achado(
                        "real-sem-d1",
                        onde,
                        "`dados.classe: real` sem `dados.decisao_d1`. A D1 e acto do "
                        "fundador e esta `em branco` (GoLive_Gate.md linha A1)",
                    )
                )
            if not refs:
                achados.append(
                    Achado(
                        "real-sem-apd-ref",
                        onde,
                        "`dados.classe: real` sem nenhum `apd_ref`. Sao 0 de 14 os "
                        "destinos com protocolo (GoLive_Gate.md linha B2)",
                    )
                )
        elif isinstance(decisao, str) and decisao.strip() != "":
            # Nao e defeito, mas tambem nao se cala: uma referencia de D1 num
            # ambiente sintetico quer dizer que alguem parou a meio da passagem.
            achados.append(
                Achado(
                    "d1-sem-classe-real",
                    onde,
                    f"ha `decisao_d1` ({decisao!r}) e a classe continua {classe!r}; "
                    "ou a passagem ficou a meio, ou a referencia esta no ambiente errado",
                )
            )

        if isinstance(decisao, str) and not DECISAO_D1.fullmatch(decisao):
            achados.append(
                Achado(
                    "d1-mal-formada",
                    onde,
                    f"`decisao_d1` {decisao!r} fora de D1/<AAAA-MM-DD>/<slug>",
                )
            )
        for ref in refs:
            if not isinstance(ref, str) or not APD_REF.fullmatch(ref):
                achados.append(
                    Achado(
                        "apd-ref-mal-formada",
                        onde,
                        f"`apd_ref` {ref!r} fora da forma de KAM-011 "
                        "(ate 128 caracteres, sem espacos)",
                    )
                )

        etiquetas = (bruto.get("custo") or {}).get("etiquetas") or {}
        etiqueta = etiquetas.get("kamba_data_class") if isinstance(etiquetas, dict) else None
        if etiqueta != classe:
            achados.append(
                Achado(
                    "etiqueta-de-classe-divergente",
                    onde,
                    f"`custo.etiquetas.kamba_data_class` e {etiqueta!r} e "
                    f"`dados.classe` e {classe!r}; uma etiqueta que minta sobre o que "
                    "o recurso guarda e pior do que nenhuma",
                )
            )
    return achados


def _regra_restauro(dados: Dados) -> list[Achado]:
    """O criterio 3: uma copia de `prod` nao se restaura noutro ambiente."""
    achados = []
    for ambiente, bruto in sorted(dados.ambientes.items()):
        onde = f"infra/envs/{ambiente}/env.yaml"
        origens = (bruto.get("dados") or {}).get("restauro_de")
        if origens is None:
            continue
        if not isinstance(origens, list):
            achados.append(
                Achado("restauro-mal-formado", onde, "`dados.restauro_de` tem de ser uma lista")
            )
            continue
        for origem in origens:
            texto = str(origem)
            if texto not in AMBIENTES:
                achados.append(
                    Achado(
                        "restauro-desconhecido",
                        onde,
                        f"`restauro_de` nomeia {texto!r}, que nao e um ambiente",
                    )
                )
            elif texto == "prod" and ambiente != "prod":
                achados.append(
                    Achado(
                        "restauro-de-prod",
                        onde,
                        f"o ambiente {ambiente!r} aceita restauro de `prod`. O doc 09 §6 "
                        "diz «nunca copia de prod», e a linha D10t do GoLive_Gate.md "
                        "depende deste controlo",
                    )
                )
    return achados


def _projectos(dados: Dados) -> dict[str, str]:
    lido = {}
    for ambiente, bruto in dados.ambientes.items():
        projecto = (bruto.get("segredos") or {}).get("projecto")
        if isinstance(projecto, str) and projecto:
            lido[ambiente] = projecto
    return lido


def _regra_projectos(dados: Dados) -> list[Achado]:
    """O criterio 5, primeira metade: o mapeamento ambiente -> projecto."""
    achados = []
    projectos = _projectos(dados)
    for ambiente in sorted(set(dados.ambientes) - set(projectos)):
        achados.append(
            Achado(
                "projecto-em-falta",
                f"infra/envs/{ambiente}/env.yaml",
                "falta `segredos.projecto`; e o mapeamento que o criterio 5 pede",
            )
        )
    for ambiente, projecto in sorted(projectos.items()):
        if projecto == PROJECTO_LOCAL and ambiente != "dev":
            achados.append(
                Achado(
                    "projecto-local-fora-de-dev",
                    f"infra/envs/{ambiente}/env.yaml",
                    f"so `dev` pode ter `segredos.projecto: {PROJECTO_LOCAL}` "
                    "(doc 09 §6: «Local, nao reutilizaveis»)",
                )
            )
    vistos: dict[str, str] = {}
    for ambiente, projecto in sorted(projectos.items()):
        if projecto in vistos:
            achados.append(
                Achado(
                    "projecto-repetido",
                    f"infra/envs/{ambiente}/env.yaml",
                    f"o projecto {projecto!r} ja e de {vistos[projecto]!r}. Dois ambientes "
                    "no mesmo projecto partilham chaves, e o doc 09 §6 exige-as distintas",
                )
            )
        else:
            vistos[projecto] = ambiente

    # A metade que o criterio 5 nomeia por extenso. NAO se assume que projectos
    # distintos bastam: calculam-se as referencias e exige-se que difiram.
    for identificador in SEGREDOS_QUE_TEM_DE_SER_DISTINTOS:
        if identificador not in dados.inventario:
            achados.append(
                Achado(
                    "segredo-nomeado-ausente-do-inventario",
                    CAMINHO_INVENTARIO,
                    f"o criterio 5 nomeia {identificador!r} e o inventario nao o tem",
                )
            )
            continue
        onde_existe = dados.inventario[identificador]
        referencias: dict[str, str] = {}
        for ambiente, projecto in sorted(projectos.items()):
            if ambiente not in onde_existe:
                continue
            referencia = f"{projecto}/{identificador.upper()}"
            if referencia in referencias.values():
                achados.append(
                    Achado(
                        "chave-partilhada-entre-ambientes",
                        f"infra/envs/{ambiente}/env.yaml",
                        f"a referencia {referencia!r} de {identificador!r} repete-se "
                        "noutro ambiente",
                    )
                )
            referencias[ambiente] = referencia
    return achados


def _regra_referencias_de_segredo(dados: Dados) -> list[Achado]:
    """O criterio 5, segunda metade: um segredo de `prod` lido em `staging`."""
    achados = []
    projectos = _projectos(dados)
    if not projectos:
        return achados
    por_projecto = {projecto: ambiente for ambiente, projecto in projectos.items()}
    # Um padrao por projecto, e a segunda metade tem de ser um `id` do
    # inventario em maiusculas: assim a palavra «prod» em prosa nao dispara
    # nada, e o que dispara e `prod/META_APP_SECRET`.
    #
    # A OLHADA NEGATIVA NO FIM NAO E ZELO: sem ela, `prod/LEIA-ME` casava
    # `prod/LEIA` — a corrida para de maiusculas no hifen, que e fronteira de
    # palavra — e dava um achado `segredo-fora-do-inventario` sobre um caminho
    # de ficheiro. Foi um teste proprio que o apanhou
    # (`test_a_palavra_prod_em_prosa_nao_dispara`), e o padrao passou a exigir
    # que a corrida de maiusculas **acabe ali**: o caracter seguinte nao pode
    # continuar um nome nem abrir outro segmento de caminho.
    padrao = re.compile(
        r"\b("
        + "|".join(re.escape(p) for p in sorted(por_projecto))
        + r")/([A-Z][A-Z0-9_]*)(?![-/.\w])"
    )
    for caminho, texto in sorted(dados.ficheiros.items()):
        # So configuracao. A razao esta em `EXTENSOES_DE_CONFIGURACAO`.
        if not caminho.endswith(EXTENSOES_DE_CONFIGURACAO):
            continue
        partes = caminho.split("/")
        dono = partes[2] if len(partes) > 3 and partes[:2] == ["infra", "envs"] else None
        for numero, linha in enumerate(texto.splitlines(), start=1):
            for projecto, maiusculas in padrao.findall(linha):
                identificador = maiusculas.lower()
                if identificador not in dados.inventario:
                    achados.append(
                        Achado(
                            "segredo-fora-do-inventario",
                            f"{caminho}:{numero}",
                            f"{projecto}/{maiusculas} nao corresponde a nenhum `id` de "
                            f"{CAMINHO_INVENTARIO}",
                        )
                    )
                    continue
                ambiente_da_referencia = por_projecto[projecto]
                if dono is None:
                    achados.append(
                        Achado(
                            "segredo-fora-de-um-ambiente",
                            f"{caminho}:{numero}",
                            f"referencia {projecto}/{maiusculas} fora de infra/envs/<ambiente>/. "
                            "Um modulo nao sabe de que ambiente e: a referencia entra por "
                            "variavel, derivada de `segredos.projecto`",
                        )
                    )
                elif ambiente_da_referencia != dono:
                    achados.append(
                        Achado(
                            "segredo-de-outro-ambiente",
                            f"{caminho}:{numero}",
                            f"referencia {projecto}/{maiusculas} (de {ambiente_da_referencia!r}) "
                            f"dentro de infra/envs/{dono}/. O criterio 5 exige que isto falhe",
                        )
                    )
                elif dono not in dados.inventario[identificador]:
                    achados.append(
                        Achado(
                            "segredo-nao-existe-no-ambiente",
                            f"{caminho}:{numero}",
                            f"{identificador!r} existe em {dados.inventario[identificador]} "
                            f"e nao em {dono!r} (ver {CAMINHO_INVENTARIO})",
                        )
                    )
    return achados


def _regra_portabilidade(dados: Dados) -> list[Achado]:
    """O criterio 6: nenhum recurso de fornecedor fora da costura."""
    achados = []
    for caminho, texto in sorted(dados.ficheiros.items()):
        if not caminho.endswith(".tf"):
            continue
        if fnmatch.fnmatchcase(caminho, _PADRAO_DA_COSTURA):
            continue
        for achado in _BLOCO_DE_RECURSO.finditer(texto):
            numero = texto[: achado.start()].count("\n") + 1
            achados.append(
                Achado(
                    "recurso-fora-da-costura",
                    f"{caminho}:{numero}",
                    f"bloco `{achado.group(1)}` fora de `infra/modules/provider-*/`. "
                    "O criterio 6 pede 0 recursos proprietarios sem equivalente, e a "
                    "forma de o garantir e nenhum recurso fora da costura "
                    "(ADR-L007 §2)",
                )
            )
    return achados


def _regra_dns(dados: Dados) -> list[Achado]:
    achados = []
    for ambiente, bruto in sorted(dados.ambientes.items()):
        ttl = (bruto.get("dns") or {}).get("ttl_segundos")
        if not isinstance(ttl, int) or isinstance(ttl, bool):
            achados.append(
                Achado(
                    "ttl-ausente",
                    f"infra/envs/{ambiente}/env.yaml",
                    "falta `dns.ttl_segundos` (inteiro). O passo «DNS» entra no "
                    "orcamento de RTO do doc 09 §8.2",
                )
            )
        elif ttl > TTL_MAXIMO_PROPOSTO:
            achados.append(
                Achado(
                    "ttl-acima-do-proposto",
                    f"infra/envs/{ambiente}/env.yaml",
                    f"`dns.ttl_segundos` e {ttl} e o tecto *proposto* pelo bloco do "
                    f"KAM-075 e {TTL_MAXIMO_PROPOSTO}",
                )
            )
    return achados


#: As regras, na ordem em que correm. A ordem nao muda o resultado — cada uma
#: le o `Dados` e nao escreve nada —, e esta e a dos criterios de aceitacao.
REGRAS = (
    _regra_ambientes_existem,
    _regra_esquema,
    _regra_matriz,
    _regra_classe_de_dados,
    _regra_restauro,
    _regra_projectos,
    _regra_referencias_de_segredo,
    _regra_portabilidade,
    _regra_dns,
)


def avaliar(dados: Dados) -> list[Achado]:
    """Corre as regras. Puro: nao toca no disco, o que e o que o canario usa."""
    achados: list[Achado] = []
    for regra in REGRAS:
        achados.extend(regra(dados))
    return achados


def varrer(raiz: Path) -> tuple[list[Achado], dict[str, int]]:
    dados = carregar(raiz)
    return avaliar(dados), {
        "ambientes": len(dados.ambientes),
        "linhas": len(dados.linhas_da_matriz) + len(dados.linhas_acrescentadas),
        "segredos": len(dados.inventario),
        "ficheiros": len(dados.ficheiros),
        "regras": len(REGRAS),
    }
