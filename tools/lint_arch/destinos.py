"""Os clientes de saida para subprocessadores, e quem consulta o *gate* (KAM-069).

O criterio 4 do bloco pede: «O *gate* e invocado antes de LLM, STT, *embeddings*,
*backups*, CDN, observabilidade e e-mail/SMS; **um teste de arquitectura falha se
um cliente desses fornecedores for importado fora do modulo do *gate***.»

## A forma que a letra sugere seria um gate que passa por vazio

A leitura literal — «recusar o *import* de um SDK de fornecedor» — e verdadeira
e **inutil hoje**, e isso mede-se: nao ha **nenhum** SDK de fornecedor no
repositorio. O canon escreve-o por extenso para o AGR («nenhum SDK de fornecedor
entra no AGR, e o pacote `litellm` tambem nao»), e a varredura confirma-o para a
arvore toda: zero *imports* de `anthropic`, `openai`, `groq-sdk`, `@aws-sdk/*`,
`twilio`, `@sendgrid/*` ou `@sentry/*`. Um *lint* assim nascia verde e ficava
verde, e e a classe de defeito que esta casa recusa — «uma superficie com zero
ficheiros passa sempre».

## O que este modulo faz em vez disso, e e nas duas direccoes

Um **inventario fechado de clientes de saida**, com a forma dos outros
inventarios desta casa (o `TABELAS` do *gate* 8, o `INVENTARIO` do *gate* 7, o
`ci/rls_exceptions.yaml` do *gate* 6):

  descoberta   um ficheiro de codigo em `services/*/src`, `packages/*/src` ou
               `libs/*/src` que contenha o **FQDN de um subprocessador** ou um
               *import* de um **SDK de fornecedor** e, e nao esteja no
               inventario, e achado. E a metade que apanha o cliente novo.

  declaracao   cada entrada do inventario diz se **consulta o *gate*** e, quando
               nao consulta, **quem e o credor**. Uma entrada que diga que
               consulta e cujo ficheiro nao refira o modulo do *gate* e achado:
               e a metade que apanha a chamada **retirada**. Uma entrada cujo
               ficheiro ja nao exista tambem e achado — um inventario com
               entradas mortas descreve uma arvore que nao existe.

A segunda direccao e a que tem valor hoje: hoje **um** dos sete pontos consulta o
*gate*, e se alguem lhe tirar a chamada isto fica vermelho. **Desde o KAM-120 ha
uma segunda entrada que consulta**, a Foto AI, que nao e um dos sete pontos do
criterio: e a finalidade `imagem`, que a revisao `foto_de_produtos` acrescenta.

## O que isto NAO apanha, e diz-se para nao se ler como mais do que e

Um cliente que receba o anfitriao do **ambiente** em vez de o escrever na fonte.
Nao ha FQDN para descobrir, e nenhum *import* o denuncia. O que devia cobrir
esse caminho e o regime dos `egress.yaml` — e ele **nao cobre** `packages/` nem
`libs/`: medido em
`docs/tecnica/evidencia/validacao/Mapa_Tratamentos_v1.md` §0, zero ficheiros. A
aplicacao na rede e o **KAM-076** e nao esta feita. Credor escrito, e nao
disfarcado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Onde se procura: codigo de producao, e nao testes nem documentos.
#:
#: Os testes ficam de fora de proposito — um teste que cite um FQDN para o
#: afirmar numa asercao nao e um cliente, e e o caso do
#: `packages/core-ts/tests/outbound.limites.test.ts`. Os `*.yaml` de `egress`
#: tambem: eles sao a **lista de saidas**, nao quem sai.
AMBITO = ("services/", "packages/", "libs/")
DENTRO_DE = ("/src/",)
SUFIXOS = (".ts", ".tsx", ".py", ".mjs", ".cjs", ".js")

#: Os FQDN dos subprocessadores que servem APIs, do `docs/tecnica/08` §8.3.2.
#:
#: **Nao e a lista de subprocessadores** — e a dos que tem um anfitriao que se
#: escreve numa constante. O alojamento, o CDN, o facilitador, a facturacao e o
#: e-mail/SMS nao estao aqui porque nenhum tem FQDN fixo: o anfitriao deles vem
#: da configuracao, que e precisamente o caminho que a nota do modulo declara
#: nao apanhar.
FQDN_DE_SUBPROCESSADOR = (
    "api.anthropic.com",
    "api.openai.com",
    "generativelanguage.googleapis.com",
    "api.groq.com",
    "graph.facebook.com",
)

#: *Imports* de SDK de fornecedor. **Zero ocorrencias hoje, e e medido.**
#:
#: Ficam porque a barreira e para o dia em que alguem acrescentar um, e porque a
#: forma e o que a torna barata: casa um `import`/`from` real e nao a palavra
#: solta — `litellm_virtual_key` e o nome de um segredo e nao um SDK, e um
#: `substring` apanhava-o em cinco ficheiros do AGR.
IMPORT_DE_SDK = re.compile(
    r"^\s*(?:from|import)\s+"
    r"(?:anthropic|openai|groq|litellm|boto3|minio|sendgrid|twilio|sentry_sdk)\b"
    r"|from\s+[\"'](?:anthropic|openai|@anthropic-ai/|@google/generative-ai|"
    r"groq-sdk|litellm|@aws-sdk/|minio|@sendgrid/|twilio|@sentry/)"
    r"|require\([\"'](?:anthropic|openai|@anthropic-ai/|groq-sdk|@aws-sdk/|"
    r"minio|@sendgrid/|twilio|@sentry/)",
    re.MULTILINE,
)

#: A **chamada** do *gate*, e nao o nome do modulo.
#:
#: A primeira versao desta regra procurava a cadeia `destinos`, e isso passava
#: com a chamada retirada: a palavra aparece em comentarios, no nome do
#: parametro `porta_de_destinos` e na anotacao de tipo. O que tem de estar la e
#: a invocacao — `.autorizar(` —, que e o unico sitio onde o *gate* corre, mais
#: o `import` do modulo que a define.
CHAMADA_DO_GATE = ".autorizar("
IMPORTA_O_GATE = re.compile(
    r"^\s*(?:from|import)\s+.*\bdestinos\b", re.MULTILINE
)


@dataclass(frozen=True)
class ClienteDeSaida:
    """Um caminho de saida para um subprocessador, declarado."""

    #: As finalidades de `platform.tenant_destinations.purpose` (revisao `0036`)
    #: que este caminho de saida serve.
    #:
    #: **Plural, e era singular.** A revisao adversarial mediu o que isso
    #: custava: com **uma** cadeia, o cliente de LLM — que e o unico que consulta
    #: o *gate* — so podia declarar `conversa`, e a `embeddings` e a `visao`
    #: apareciam como nao cobertas. A `embeddings` estava mesmo em
    #: `FINALIDADES_SEM_CLIENTE`, com credor KAM-063, quando o
    #: `finalidade_de(papel)` do AGR ja a mapeia (`embed` -> `embeddings`) e a
    #: chamada passa pelo mesmo `.autorizar(`. Era **um numero velho num
    #: inventario fechado**, e na direccao que esta casa nao aceita: a dizer que
    #: o *gate* cobre menos do que cobre.
    finalidades: tuple[str, ...]
    #: `True` quando o ficheiro consulta o *gate* antes de sair.
    consulta_o_gate: bool
    #: `KAM-NNN` quando nao consulta. Vazio quando consulta.
    credor: str
    #: Uma frase que sobreviva a sair o autor.
    razao: str


#: O inventario. **Fechado**, e crescer e uma alteracao visivel.
#:
#: Sete finalidades no criterio 4 e **uma** linha a consultar o *gate* entre
#: elas (a segunda que consulta, a da Foto AI, nao e desses sete): e a
#: medicao que a caixa daquele criterio leva, e esta tabela e onde ela vive em
#: vez de viver numa frase de um bloco.
CLIENTES_DE_SAIDA: dict[str, ClienteDeSaida] = {
    "services/agr/src/kamba_agr/llm/cliente.py": ClienteDeSaida(
        finalidades=("conversa", "embeddings", "visao"),
        consulta_o_gate=True,
        credor="",
        razao=(
            "O unico cliente de saida do repositorio que consulta o gate. Chama "
            "`autorizar` para **todos** os fornecedores do alias antes do pedido "
            "(dicionario secao 3.29: o fallback e do router e o cliente nao "
            "escolhe quem serve), e nao escreve FQDN nenhum — fala com o proxy "
            "interno por `KAMBA_LLM_PROXY_URL`."
        ),
    ),
    "libs/py-core/src/kamba_core/foto/servico.py": ClienteDeSaida(
        finalidades=("imagem",),
        consulta_o_gate=True,
        credor="",
        razao=(
            "O trabalhador da Foto AI (KAM-120). Chama `autorizar` com a "
            "finalidade `imagem` para **cada** fornecedor de imagem antes de lhe "
            "enviar a foto, e so depois da minimizacao local (EXIF, rostos e "
            "matriculas). Nao escreve FQDN nenhum: fala com o `ImageProvider`, "
            "cujos adaptadores reais nascem com a decisao do bake-off."
        ),
    ),
    "packages/core-ts/src/outbound/cliente.ts": ClienteDeSaida(
        finalidades=("canal",),
        consulta_o_gate=False,
        credor="KAM-015",
        razao=(
            "O cliente da Graph da Meta, e o primeiro codigo que sai para lá. "
            "Fixa `graph.facebook.com` numa constante e monta um corpo que leva "
            "o telefone do destinatario quando nao ha identificador da Meta. "
            "**Nao consulta o gate**, e o gate e Python: ligar os dois e um "
            "ticket de saida de canal e nao deste. Hoje nenhum servico o "
            "instancia (medido em `Mapa_Tratamentos_v1.md` secao 0)."
        ),
    ),
    "packages/core-ts/src/onboarding/graph.ts": ClienteDeSaida(
        finalidades=("canal",),
        consulta_o_gate=False,
        credor="KAM-016",
        razao=(
            "O cliente da Graph do Embedded Signup: troca o code por token e "
            "subscreve campos de webhook. Leva o FQDN como base configuravel e "
            "**nao** dados de cliente — o que sai e o code do dono. Mesmo "
            "credor de camada que o `outbound/cliente.ts`."
        ),
    ),
    "services/onboarding-web/src/pagina_guia.ts": ClienteDeSaida(
        finalidades=("canal",),
        consulta_o_gate=False,
        credor="KAM-102",
        razao=(
            "A pagina do passo guiado do Embedded Signup (KAM-093). **O "
            "servidor nao sai para a Meta daqui**: o FQDN esta na CSP, que "
            "autoriza o navegador do dono a carregar o SDK e a abrir o popup "
            "onde ele se autentica na Meta, presente. O que passa e o IP e o "
            "User-Agent do dono, no passo em que ele fala com a Meta "
            "directamente; o code volta pelo servidor e segue para o GWY "
            "(`onboarding/graph.ts`). Nao ha chamada ao gate porque nao ha "
            "pedido do servidor a autorizar; o enquadramento desta relacao "
            "directa do dono com a Meta e o do Tech Provider."
        ),
    ),
    "packages/core-ts/src/storage/s3.ts": ClienteDeSaida(
        finalidades=("alojamento", "copias_de_seguranca"),
        consulta_o_gate=False,
        credor="KAM-011",
        razao=(
            "A porta de armazenamento de objectos. Sem FQDN na fonte — o "
            "anfitriao vem de `KAMBA_STORAGE_*` —, pelo que a descoberta nao a "
            "veria; entra por declaracao. O que a barra em `prod` e o "
            "`DestinoSemApdRefError` do `storage/config.ts`, que e a forma que o "
            "KAM-011 entregou antes de haver tabela: recusa o arranque com "
            "destino fora de Angola sem `apd_ref`."
        ),
    ),
    "libs/py-core/src/kamba_core/storage/s3.py": ClienteDeSaida(
        finalidades=("alojamento", "copias_de_seguranca"),
        consulta_o_gate=False,
        credor="KAM-011",
        razao=(
            "O espelho Python da porta de armazenamento, com a mesma barreira de "
            "arranque no `storage/config.py` e pela mesma razao."
        ),
    ),
    "packages/core-ts/src/avisos/fornecedor.ts": ClienteDeSaida(
        finalidades=("otp_e_avisos_de_servico",),
        consulta_o_gate=False,
        credor="KAM-115",
        razao=(
            "A declaracao do fornecedor de e-mail, com o gate de `prod` que o "
            "criterio 8 do KAM-115 escreve como alternativa ao inventario: sem "
            "`apd_ref`, em `prod`, o servico nao arranca. **Nao e um cliente** — "
            "nao ha adaptador de envio —, e entra no inventario porque e o sitio "
            "onde esta finalidade e barrada hoje."
        ),
    ),
    "packages/core-ts/src/sms/fornecedor.ts": ClienteDeSaida(
        finalidades=("otp_e_avisos_de_servico",),
        consulta_o_gate=False,
        credor="KAM-116",
        razao=(
            "O mesmo para o agregador de SMS, com um degrau a mais: exige estado "
            "`autorizado` e nao so `apd_ref`. Tambem nao e um cliente — o "
            "`FakeSmsProvider` e o que CI e `staging` usam."
        ),
    ),
}

#: As finalidades que **nenhuma** entrada do inventario serve, com o ticket ou a
#: decisao que as vai trazer. Nao e uma dispensa: e a conta que a caixa do
#: criterio 4 leva, escrita onde um `grep` a encontra.
#:
#: **Sao seis, e eram cinco e erradas.** A revisao adversarial mostrou que a
#: lista anterior punha a `embeddings` aqui — quando o cliente de LLM ja a cobre
#: pelo `papel: embed` — e deixava de fora quatro que nenhuma entrada serve. A
#: causa era o `ClienteDeSaida.finalidade` ser **uma** cadeia: uma entrada que
#: serve tres finalidades so podia declarar uma, e a conta fechava por acidente.
#:
#: Deriva-se das catorze menos as declaradas, e o
#: `test_as_finalidades_sem_cliente_sao_as_do_dominio_menos_as_declaradas` confronta
#: as duas **nos dois sentidos**. A lista escrita a mao fica porque leva o
#: **credor**, que nao se deriva de nada.
FINALIDADES_SEM_CLIENTE = {
    "entrega_de_conteudo": "D12",
    "facturacao": "D7",
    "observabilidade": "KAM-080",
    "pagamentos": "D4",
    "segredos": "KAM-104",
    "transcricao": "KAM-036",
}


def _ficheiros(root: Path, caminhos: list[str]) -> list[str]:
    return [
        caminho
        for caminho in caminhos
        if caminho.startswith(AMBITO)
        and any(dentro in f"/{caminho}" for dentro in DENTRO_DE)
        and caminho.endswith(SUFIXOS)
    ]


def check(root: Path, caminhos: list[str] | None = None) -> list[str]:
    """Os desvios do inventario de clientes de saida. Lista vazia = conforme."""
    problemas: list[str] = []

    # --- declaracao: cada entrada existe, e diz a verdade -------------------
    for relativo, cliente in sorted(CLIENTES_DE_SAIDA.items()):
        caminho = root / relativo
        if not caminho.is_file():
            problemas.append(
                f"{relativo}: entrada morta no inventario de clientes de saida "
                "do KAM-069 — o ficheiro nao existe. Uma entrada que descreve "
                "uma arvore que ja nao ha esconde que o caminho de saida "
                "desapareceu (ou mudou de nome)"
            )
            continue
        if cliente.consulta_o_gate:
            fonte = caminho.read_text(encoding="utf-8", errors="replace")
            faltam = []
            if CHAMADA_DO_GATE not in fonte:
                faltam.append(f"a chamada `{CHAMADA_DO_GATE}`")
            if not IMPORTA_O_GATE.search(fonte):
                faltam.append("o `import` do modulo do *gate*")
            if faltam:
                problemas.append(
                    f"{relativo}: o inventario do KAM-069 declara que consulta o "
                    f"*gate* de transferencia e falta {' e '.join(faltam)}. Se a "
                    "chamada foi retirada, nenhum dado pessoal passa a ter "
                    "barreira antes de sair de Angola (ADR-008)"
                )
        elif not cliente.credor:
            problemas.append(
                f"{relativo}: nao consulta o *gate* e nao tem credor escrito. "
                "Uma caixa que fica aberta leva o ticket que a fecha"
            )

    # --- descoberta: nenhum cliente novo fora do inventario -----------------
    #
    # **Fora de um repositorio, a descoberta nao corre e isso e um achado**, nao
    # um silencio. A primeira versao desta metade levantava `OSError` sempre que
    # o `git` nao respondesse, e isso quebrou sete ensaios do `test_structure.py`
    # que chamam o `structure.check` sobre arvores temporarias — arvores que nao
    # sao repositorios, e onde nao ha «arvore seguida pelo git» para varrer.
    #
    # A distincao que ficou e a que importa: **nao ser um repositorio** nao e
    # falha do `git`, e nesse caso diz-se que a descoberta nao correu; **falhar
    # dentro de um** e, e ai levanta-se, pela razao do achado 9 — varrer zero
    # ficheiros e reportar conforme e a classe «uma superficie com zero
    # ficheiros passa sempre» que a nota deste modulo recusa.
    if caminhos is None:
        if not _e_repositorio(root):
            problemas.append(
                f"{root}: nao e uma arvore seguida pelo git, pelo que a "
                "descoberta de clientes de saida **nao correu**. A metade da "
                "declaracao correu; a da descoberta precisa do `git ls-files`, e "
                "varrer o disco em vez dele punha `node_modules/` e `dist/` na "
                "varredura (KAM-069, criterio 4)"
            )
            return problemas
        caminhos = _do_git(root)
    for relativo in _ficheiros(root, caminhos):
        if relativo in CLIENTES_DE_SAIDA:
            continue
        caminho = root / relativo
        if not caminho.is_file():
            continue
        fonte = caminho.read_text(encoding="utf-8", errors="replace")
        achados = [fqdn for fqdn in FQDN_DE_SUBPROCESSADOR if fqdn in fonte]
        if IMPORT_DE_SDK.search(fonte):
            achados.append("import de SDK de fornecedor")
        if achados:
            problemas.append(
                f"{relativo}: cliente de saida fora do inventario do KAM-069 "
                f"({', '.join(achados)}). Declare-o em "
                "`tools/lint_arch/destinos.py`, com a finalidade de "
                "`tenant_destinations.purpose` e — se nao consultar o *gate* de "
                "transferencia — o credor que o vai ligar (ADR-008, criterio 4)"
            )
    return problemas


def _e_repositorio(root: Path) -> bool:
    """`True` se o `root` esta dentro de uma arvore de trabalho do git.

    Separado do `_do_git` de proposito: as duas perguntas tem respostas
    diferentes e consequencias diferentes. «Nao e um repositorio» e um facto
    sobre o sitio — as arvores temporarias dos ensaios do `structure.py` sao
    assim —, e «o `git` falhou num repositorio» e uma avaria que nao pode passar
    por vazio.
    """
    import subprocess

    saida = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return saida.returncode == 0 and saida.stdout.strip() == "true"


def _do_git(root: Path) -> list[str]:
    """A arvore seguida pelo git, como no `codeowners`.

    **Nao e um `glob` do disco**, e a razao e a mesma que o `superficies.py` do
    `canon_lint` escreve: um `node_modules/` ou um `dist/` por versionar enchia a
    varredura de ficheiros de terceiros, e um deles com um FQDN de fornecedor
    dava um achado que ninguem pode corrigir.
    """
    import subprocess

    saida = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    # **Falha fechada, e nao lista vazia.** A primeira versao devolvia `[]` se o
    # `git` nao respondesse, e isso punha a metade da descoberta a varrer zero
    # ficheiros e a reportar conforme — a classe «uma superficie com zero
    # ficheiros passa sempre» que a nota deste modulo recusa. Apanhado pela
    # revisao adversarial. E a mesma escolha do `ficheiros_do_git` do
    # `codeowners.py`, que levanta `OSError` em vez de recorrer ao `os.walk`.
    if saida.returncode != 0:
        raise OSError(
            f"`git ls-files` saiu com {saida.returncode} em {root}: sem a arvore "
            "seguida pelo git nao ha como descobrir um cliente de saida novo, e "
            "varrer zero ficheiros reportava conforme (KAM-069, criterio 4)"
        )
    return [linha for linha in saida.stdout.splitlines() if linha]
