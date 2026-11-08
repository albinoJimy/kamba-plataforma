"""O canario do `backup_lint`: a prova de que o *lint* morde (KAM-079).

Um *lint* verde sobre uma arvore limpa **nao prova nada**: prova que a arvore
esta limpa, ou que o *lint* nao olha. Este repositorio ja pagou duas vezes por
confiar num verde — o *gate* 9 esteve sete PRs sem nada que o provasse, e o
primeiro canario do *gate* 3b dava verde com a lista de casos vazia
(`docs/ci.md` §3).

## Por mutacao, e nao por *fixtures*

A razao e a do `tools/compose_prod/canario.py`: as regras daqui sao sobre
**relacoes entre cinco ficheiros**, e uma *fixture* por regra nao e um ficheiro
— e uma arvore. Trinta copias da arvore divergem da real **sem que nada avise**,
e o canario passaria a verde sobre uma configuracao que ja nao se parece com a
que o *lint* verifica.

Por mutacao e o contrario: parte-se da arvore **real**, muda-se uma coisa, e
exige-se o achado.

## Os tres fechos desta forma

1. **Uma mutacao que deixou de se aplicar** passa a verde por nao ter medido
   nada. Dai cada mutacao ter de **encontrar o texto** que troca: se nao
   encontra, falha com `nao se aplica`, nunca um verde.
2. **Vermelho pela regra errada** e sorte, nao cobertura. Cada caso declara as
   regras que espera, e exige-se que os achados sejam **exactamente** essas.
3. **Uma regra sem canario** fica em silencio. O `MINIMO_POR_REGRA` exige que
   toda a regra de `lint.REGRAS` tenha caso.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import lint


class NaoSeAplica(RuntimeError):
    """A mutacao ja nao encontra o texto que ia trocar."""


class Copia:
    """A arvore copiada: so o que o `varrer` le."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz

    def ler(self, ficheiro: str) -> str:
        caminho = self.raiz / ficheiro
        if not caminho.is_file():
            raise NaoSeAplica(f"{ficheiro} nao existe")
        return caminho.read_text(encoding="utf-8")

    def escrever(self, ficheiro: str, texto: str) -> None:
        caminho = self.raiz / ficheiro
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto, encoding="utf-8", newline="\n")

    def trocar(self, ficheiro: str, padrao: str, novo: str, quantas: int = 1) -> None:
        """Troca `padrao` (expressao regular) por `novo`. Exige que bata."""
        texto = self.ler(ficheiro)
        resultado, encontradas = re.subn(
            padrao, novo.replace("\\", "\\\\"), texto, count=quantas, flags=re.MULTILINE
        )
        if encontradas != quantas or resultado == texto:
            raise NaoSeAplica(
                f"{ficheiro}: /{padrao}/ bateu {encontradas} vez(es) e "
                f"esperavam-se {quantas}"
            )
        self.escrever(ficheiro, resultado)

    def trocar_todas(self, ficheiro: str, padrao: str, novo: str) -> None:
        """Como o `trocar`, mas para «todas as que houver» — exigindo >= 1.

        Existe por um caso: o `backup_repo_cifra_passphrase` aparece mais do que
        uma vez no inventario de segredos (o `id` e a referencia na prosa), e o
        *lint* le-o por presenca de texto. Trocar so a primeira deixava o nome
        no ficheiro e o caso passava a verde sem medir nada.
        """
        texto = self.ler(ficheiro)
        resultado, encontradas = re.subn(
            padrao, novo.replace("\\", "\\\\"), texto, flags=re.MULTILINE
        )
        if not encontradas:
            raise NaoSeAplica(f"{ficheiro}: /{padrao}/ nao bateu nenhuma vez")
        self.escrever(ficheiro, resultado)

    def acrescentar(self, ficheiro: str, texto: str) -> None:
        self.escrever(ficheiro, self.ler(ficheiro).rstrip("\n") + "\n" + texto)

    def apagar_linha(self, ficheiro: str, padrao: str) -> None:
        texto = self.ler(ficheiro)
        linhas = texto.splitlines()
        mantidas = [l for l in linhas if not re.match(padrao, l)]
        if len(mantidas) == len(linhas):
            raise NaoSeAplica(f"{ficheiro}: nenhuma linha casa /{padrao}/")
        self.escrever(ficheiro, "\n".join(mantidas) + "\n")


@dataclass(frozen=True)
class Caso:
    codigo: str
    #: As regras que **tem** de disparar, e as unicas que podem.
    espera: frozenset[str]
    descricao: str
    mutacao: Callable[[Copia], None]
    #: Regras que podem ou nao disparar, sem falhar o caso. Cada uso tem a razao
    #: escrita no proprio caso.
    tolera: frozenset[str] = field(default=frozenset())


#: Um destino **completo e valido**, para as mutacoes que precisam de um. Esta
#: aqui para que cada mutacao mude **uma** coisa: um destino acrescentado sem
#: `fqdn`, `jurisdicao`, `dominio_de_falha`, `credor` e `ticket` disparava cinco
#: achados da mesma regra e nao provava nenhum deles em isolamento.
#:
#: O FQDN e `.invalid`, que a RFC 2606 reserva para nunca resolver: um nome
#: plausivel aqui era um destino de backup escrito num repositorio publico.
_DESTINO_COMPLETO = """destinos:
  - nome: repo1
    fqdn: backup.exemplo.invalid
    host: backup.exemplo.invalid
    caminho: /var/lib/pgbackrest
    jurisdicao: angola
    dominio_de_falha: outro-dc
    apd_ref: APD/2026/0001
    classe_de_dados: real
    credor: KAM-079
    ticket: KAM-079
"""


CASOS: tuple[Caso, ...] = (
    # ------------------------------------------------------- a cifra
    Caso(
        "cifra-fraca-no-manifesto",
        frozenset({"cifra-fraca", "cifra-divergente"}),
        "a cifra declarada desce de AES-256 para AES-128",
        # As duas regras sao verdade e as duas sao o ponto: a cifra fica fraca
        # **e** as duas superficies passam a discordar. Separa-las exigia mudar
        # os dois ficheiros, que e mudar duas coisas.
        lambda c: c.trocar(lint.COBERTURA, r"^  cifra: aes-256-cbc$", "  cifra: aes-128-cbc"),
    ),
    Caso(
        "cifra-fraca-no-conf",
        frozenset({"cifra-fraca"}),
        "o `repo1-cipher-type` desce para AES-128",
        lambda c: c.trocar(
            lint.PGBACKREST,
            r"^repo1-cipher-type=aes-256-cbc$",
            "repo1-cipher-type=aes-128-cbc",
        ),
    ),
    Caso(
        "cifra-ausente",
        frozenset({"cifra-fraca"}),
        "a cifra do repositorio desaparece — o pgBackRest nao cifra por omissao",
        lambda c: c.apagar_linha(lint.PGBACKREST, r"^repo1-cipher-type="),
    ),
    Caso(
        "cifra-divergente",
        frozenset({"cifra-divergente"}),
        "as duas superficies dizem AES-256 em modos diferentes",
        lambda c: c.trocar(
            lint.PGBACKREST,
            r"^repo1-cipher-type=aes-256-cbc$",
            "repo1-cipher-type=aes-256-gcm",
        ),
    ),
    # ------------------------------------------------------- os segredos
    Caso(
        "segredo-em-claro",
        frozenset({"segredo-em-claro"}),
        "a passphrase da cifra entra no ficheiro com valor",
        # A regra inverteu-se depois de a revisao adversarial medir que o
        # pgBackRest **nao expande** `${...}` dentro do ficheiro: a chave tem de
        # estar **ausente** e vir do `PGBACKREST_REPO1_CIPHER_PASS`. A mutacao
        # e, por isso, acrescentar a chave e nao estragar-lhe o valor.
        lambda c: c.acrescentar(
            lint.PGBACKREST, "repo1-cipher-pass=umaFraseQualquer\n"
        ),
    ),
    Caso(
        "valor-de-implantacao",
        frozenset({"valor-de-implantacao"}),
        "o destino do `repo1` entra escrito no ficheiro, que a D1 nao decidiu",
        # Nao e segredo, e por isso tem codigo proprio: um FQDN escrito aqui nao
        # vaza nada, mas parece uma decisao que ninguem tomou — e o pgBackRest
        # le-o literalmente, pelo que passaria a ser o destino real.
        lambda c: c.acrescentar(
            lint.PGBACKREST, "repo1-host=backup.exemplo.invalid\n"
        ),
    ),
    Caso(
        "ambiente-nao-documentado",
        frozenset({"ambiente-nao-documentado"}),
        "o cabecalho deixa de nomear o `PGBACKREST_*` de uma chave ausente",
        # A metade que impede a outra de ser inutil: uma chave ausente sem nada
        # que diga de onde vem le-se como uma chave esquecida, e quem implanta
        # nao tem como saber que lhe falta dar o caminho.
        lambda c: c.trocar_todas(
            lint.PGBACKREST, r"PGBACKREST_REPO1_PATH", "PGBACKREST_REPO1_CAMINHO"
        ),
    ),
    Caso(
        "chave-em-falta",
        frozenset({"chave-em-falta"}),
        "o `repo1-retention-archive` desaparece: a janela de PITR passa a efeito",
        # Sem a chave, a expiracao do arquivo cai no `repo1-retention-diff`, e a
        # janela de PITR deixa de ser um numero declarado para ser o efeito de
        # outra chave — medido na ajuda do binario.
        lambda c: c.apagar_linha(lint.PGBACKREST, r"^repo1-retention-archive="),
    ),
    Caso(
        "segredo-fora-do-inventario",
        frozenset({"segredo-fora-do-inventario"}),
        "a chave de cifra sai do inventario de segredos",
        lambda c: c.trocar_todas(
            lint.INVENTARIO_DE_SEGREDOS,
            r"backup_repo_cifra_passphrase",
            "backup_repo_cifra_rebaptizada",
        ),
    ),
    # ------------------------------------------------------- o ciclo
    Caso(
        "archive-timeout-divergente",
        frozenset({"ciclo-divergente"}),
        "o `archive_timeout` sobe para 300 s e o manifesto continua a dizer 60",
        lambda c: c.trocar(
            lint.ARQUIVO, r"^archive_timeout = 60s$", "archive_timeout = 300s"
        ),
    ),
    Caso(
        "arquivo-desligado",
        frozenset({"arquivo-desligado"}),
        "`archive_mode` passa a `off`: sem arquivo continuo nao ha PITR",
        lambda c: c.trocar(lint.ARQUIVO, r"^archive_mode = on$", "archive_mode = off"),
    ),
    Caso(
        "pitr-divergente",
        frozenset({"pitr-divergente"}),
        "a retencao de arquivo cai de 7 para 2 dias",
        lambda c: c.trocar(
            lint.PGBACKREST, r"^repo1-retention-archive=7$", "repo1-retention-archive=2"
        ),
    ),
    Caso(
        "pitr-preso-ao-completo",
        frozenset({"pitr-preso-ao-completo"}),
        "o WAL passa a ser retido por completos: 35 dias de WAL e nao 7",
        # **Este caso prova a correccao de um defeito que o canario nao apanhou
        # na primeira versao**, e vale dizer porque: a mutacao era esta ao
        # contrario — o `full` era o esperado e o `diff` o achado. O canario
        # mordia, o lint tinha 0 achados, e a configuracao retinha WAL 35 dias
        # contra a politica do `docs/tecnica/08` §11. Uma regra invertida tem
        # canario verde: o canario prova que a regra morde, nao que esta certa.
        lambda c: c.trocar(
            lint.PGBACKREST,
            r"^repo1-retention-archive-type=diff$",
            "repo1-retention-archive-type=full",
        ),
    ),
    Caso(
        "pitr-sem-traducao",
        frozenset({"pitr-sem-traducao"}),
        "o diferencial deixa de ser diario e «7 backups = 7 dias» morre",
        # A traducao e que vale, e e ela que se muta: 7 nao e um numero errado,
        # e um numero que **deixa de significar 7 dias** sem ninguem tocar nele.
        lambda c: c.trocar(
            lint.COBERTURA, r"^  diferencial: diario$", "  diferencial: semanal"
        ),
    ),
    Caso(
        "retencao-divergente",
        frozenset({"retencao-divergente"}),
        "o `repo1-retention-full` muda e o manifesto nao",
        lambda c: c.trocar(
            lint.PGBACKREST, r"^repo1-retention-full=5$", "repo1-retention-full=3"
        ),
    ),
    Caso(
        "retencao-nao-reconcilia",
        frozenset({"retencao-nao-reconcilia", "retencao-divergente"}),
        "os 35 dias deixam de reconciliar com os completos semanais",
        # As duas: a aritmetica 5x7=35 parte-se, e o manifesto passa a discordar
        # do `.conf`. E o caso que prova que a traducao «35 dias -> 5 completos»
        # e verificada e nao apenas documentada.
        lambda c: c.trocar(
            lint.COBERTURA, r"^  retencao_completos: 5$", "  retencao_completos: 4"
        ),
    ),
    Caso(
        "numero-ilegivel",
        frozenset({"numero-ilegivel"}),
        "o `archive_timeout` passa a uma unidade que ninguem le",
        lambda c: c.trocar(
            lint.ARQUIVO, r"^archive_timeout = 60s$", "archive_timeout = um minuto"
        ),
    ),
    # ------------------------------------------------------- o repositorio
    Caso(
        "repo-no-pgdata",
        frozenset({"repo-no-pgdata"}),
        "o destino declarado aponta para dentro do volume de dados do Postgres",
        # A regra mudou de superficie com o `repo1-path`: o caminho saiu do
        # `.conf` para o ambiente, e um valor que nao vive no repositorio nao
        # pode ser verificado por nada que viva nele. Verifica-se onde o destino
        # e **declarado como dado**, que e a lista `destinos`.
        lambda c: c.trocar(
            lint.COBERTURA,
            r"^destinos: \[\]$",
            _DESTINO_COMPLETO.replace(
                "    caminho: /var/lib/pgbackrest\n",
                "    caminho: /var/lib/postgresql/backup\n",
            ),
        ),
    ),
    Caso(
        "repo-no-host-primario",
        frozenset({"repo-no-host-primario"}),
        "o destino declarado perde o `host` e passa a ser a propria maquina",
        lambda c: c.trocar(
            lint.COBERTURA,
            r"^destinos: \[\]$",
            _DESTINO_COMPLETO.replace("    host: backup.exemplo.invalid\n", ""),
        ),
    ),
    # --------------------------------------------- o comando do arquivo
    #
    # A linha que ninguem lia. Os tres casos abaixo existem por causa de um
    # defeito medido com o binario: `archive-push --async` da «invalid option»,
    # o `archive_command` nunca devolve 0, e o arquivo nunca funciona.
    Caso(
        "arquivo-com-opcao-inexistente",
        frozenset({"arquivo-com-opcao-inexistente"}),
        "volta o `--async`, que o pgBackRest recusa: o arquivo nunca funciona",
        lambda c: c.trocar(
            lint.ARQUIVO,
            r"archive-push %p'$",
            "archive-push --async %p'",
        ),
    ),
    Caso(
        "arquivo-sem-pgbackrest",
        frozenset({"arquivo-sem-pgbackrest", "arquivo-sem-archive-push",
                   "arquivo-sem-stanza"}),
        "o `archive_command` passa a um `cp`: sem cifra e sem retencao",
        # As tres sao a mesma mudanca vista de tres lados, e e por isso que o
        # caso as declara todas: um `cp` nao e o pgBackRest, nao chama
        # `archive-push` e nao tem stanza. Declarar uma so era aceitar ser
        # apanhado por sorte.
        lambda c: c.trocar(
            lint.ARQUIVO,
            r"^archive_command = .*$",
            "archive_command = 'cp %p /mnt/backup/%f'",
        ),
    ),
    Caso(
        "arquivo-sem-caminho",
        frozenset({"arquivo-sem-caminho"}),
        "o `%p` desaparece: o comando nao sabe que segmento empurrar",
        lambda c: c.trocar(
            lint.ARQUIVO,
            r"archive-push %p'$",
            "archive-push'",
        ),
    ),
    # ------------------------------------------------------- a cobertura
    Caso(
        "base-em-falta",
        frozenset({"base-em-falta"}),
        "a base `chatwoot` sai da cobertura",
        lambda c: c.trocar(
            lint.COBERTURA, r"^  - item: base chatwoot$", "  - item: base chatwoot_antiga"
        ),
    ),
    Caso(
        "item-em-falta",
        frozenset({"item-em-falta"}),
        "a ancora diaria do `audit_log` sai da cobertura",
        lambda c: c.trocar(
            lint.COBERTURA,
            r"^  - item: ancora diaria do audit_log$",
            "  - item: ancora diaria qualquer",
        ),
    ),
    Caso(
        "estado-invalido",
        frozenset({"estado-invalido"}),
        "uma linha de cobertura ganha um estado que o vocabulario nao tem",
        lambda c: c.trocar(
            lint.COBERTURA, r"^    estado: coberto$", "    estado: quase"
        ),
    ),
    Caso(
        "cobertura-sem-credor",
        frozenset({"cobertura-sem-credor"}),
        "um item `por_cobrir` perde o credor",
        lambda c: c.trocar(
            lint.COBERTURA,
            r'^    credor: "o fundador \(D6\)"$',
            '    credor: "—"',
        ),
    ),
    Caso(
        "cobertura-sem-razao",
        frozenset({"cobertura-sem-razao"}),
        "um item de cobertura perde a razao",
        # Renomeia-se a chave em vez de a esvaziar: um `razao: ""` seguido de
        # linhas indentadas e YAML invalido, e o *lint* devolvia 2 (configuracao
        # ilegivel) em vez do achado — o que esconde a regra que o caso prova.
        lambda c: c.trocar(
            lint.COBERTURA,
            r"^    razao: >-\n      Os tres ficheiros desta pasta",
            "    nota: >-\n      Os tres ficheiros desta pasta",
        ),
    ),
    # ------------------------------------------------------- os destinos
    Caso(
        "destino-sem-dono",
        frozenset({"destino-sem-dono"}),
        "um destino entra com FQDN e sem credor",
        lambda c: c.trocar(
            lint.COBERTURA,
            r"^destinos: \[\]$",
            _DESTINO_COMPLETO.replace("    credor: KAM-079\n", ""),
        ),
    ),
    Caso(
        "destino-real-sem-apd-ref",
        frozenset({"destino-real-sem-apd-ref"}),
        "um destino marcado para dados reais entra com `apd_ref: pendente`",
        # O que o caso prova e o mais importante do funil: um `apd_ref` que
        # **parece** uma referencia («pendente») nao abre o gate. O destino e
        # completo e valido em tudo o resto, para que seja esta a unica regra a
        # morder.
        lambda c: c.trocar(
            lint.COBERTURA,
            r"^destinos: \[\]$",
            _DESTINO_COMPLETO.replace("APD/2026/0001", "pendente"),
        ),
    ),
    # ------------------------------------------------------- os alertas
    Caso(
        "severidade-invalida",
        frozenset({"severidade-invalida"}),
        "o alerta do WAL passa a uma severidade que o §9.2 nao tem",
        lambda c: c.trocar(
            lint.COBERTURA, r"^  severidade: P1$", "  severidade: critica"
        ),
    ),
    Caso(
        "runbook-inexistente",
        frozenset({"runbook-inexistente"}),
        "o alerta aponta para um runbook que nao esta no disco",
        lambda c: c.trocar(lint.COBERTURA, r"^  runbook: RB-K08$", "  runbook: RB-K99"),
    ),
    Caso(
        "limite-do-wal-divergente",
        frozenset({"limite-do-wal-divergente"}),
        "o limite do alerta separa-se do RPO sem ninguem o decidir",
        lambda c: c.trocar(
            lint.COBERTURA, r"^  limite_segundos: 300$", "  limite_segundos: 600"
        ),
    ),
    Caso(
        "alerta-sem-razao",
        frozenset({"alerta-sem-razao"}),
        "o alerta do restauro perde a razao",
        lambda c: c.trocar(
            lint.COBERTURA,
            r"^  razao: >-\n    «Falha gera alerta P2»",
            "  nota: >-\n    «Falha gera alerta P2»",
        ),
    ),
    Caso(
        "falta-desactualizada",
        frozenset({"falta-desactualizada"}),
        "a entrada do catalogo volta a dizer que nao ha metrica de WAL",
        # E o caso que prova a regra mais valiosa deste *lint*: a prosa do
        # catalogo e a declaracao do codigo podem divergir **sem erro em sitio
        # nenhum**, e e a contar que isso aparece.
        # Troca-se **dentro** do escalar dobrado, e nao a chave: o `falta` do
        # catalogo e um bloco `>-` de varias linhas, e substitui-lo por um
        # escalar de uma linha deixava as linhas seguintes orfas e o YAML
        # invalido — o *lint* devolvia 2 em vez do achado.
        lambda c: c.trocar(
            lint.CATALOGO,
            r"^      ha `backup_wal_idade_segundos` declarada \(KAM-079\) e ",
            "      ha uma metrica qualquer declarada e ",
        ),
    ),
    Caso(
        "alertas-do-ticket-em-falta",
        frozenset({"alertas-do-ticket-em-falta"}),
        "uma das duas entradas do catalogo deixa de nomear o KAM-079",
        lambda c: c.trocar(
            lint.CATALOGO, r"^    credor: KAM-079$", "    credor: alguem"
        ),
    ),
    # ------------------------------------------------------- o restauro
    Caso(
        "periodo-invalido",
        frozenset({"periodo-invalido"}),
        "o periodo do restauro passa a zero: sempre em divida",
        lambda c: c.trocar(
            lint.COBERTURA, r"^  periodo_dias: 30$", "  periodo_dias: 0"
        ),
    ),
    Caso(
        "agendador-sem-estado",
        frozenset({"agendador-sem-estado"}),
        "o estado do agendador deixa de ser um dos dois valores",
        lambda c: c.trocar(
            lint.COBERTURA, r"^  agendador: ausente$", "  agendador: talvez"
        ),
    ),
    Caso(
        "agendador-sem-credor",
        frozenset({"agendador-sem-credor"}),
        "o agendador fica `ausente` sem ninguem a reclama-lo",
        lambda c: c.trocar(
            lint.COBERTURA,
            r'^  credor_do_agendador: "KAM-071/KAM-078"$',
            '  credor_do_agendador: ""',
        ),
    ),
)


#: Toda a regra de `lint.REGRAS` tem de ter caso. Uma regra nova sem canario
#: falha o canario, em vez de ficar em silencio a espera de que alguem repare.
MINIMO_POR_REGRA: dict[str, frozenset[str]] = {
    "r_cifra": frozenset({"cifra-fraca", "cifra-divergente"}),
    "r_segredo_em_claro": frozenset(
        {"segredo-em-claro", "valor-de-implantacao", "ambiente-nao-documentado"}
    ),
    "r_numeros_do_ciclo": frozenset(
        {
            "ciclo-divergente",
            "arquivo-desligado",
            "chave-em-falta",
            "pitr-divergente",
            "pitr-preso-ao-completo",
            "pitr-sem-traducao",
            "retencao-divergente",
            "retencao-nao-reconcilia",
            "numero-ilegivel",
        }
    ),
    "r_comando_do_arquivo": frozenset(
        {
            "arquivo-sem-pgbackrest",
            "arquivo-sem-archive-push",
            "arquivo-sem-caminho",
            "arquivo-com-opcao-inexistente",
            "arquivo-sem-stanza",
        }
    ),
    "r_repo_fora_do_host": frozenset({"repo-no-host-primario", "repo-no-pgdata"}),
    "r_cobertura": frozenset(
        {
            "base-em-falta",
            "item-em-falta",
            "estado-invalido",
            "cobertura-sem-credor",
            "cobertura-sem-razao",
        }
    ),
    "r_destinos": frozenset({"destino-sem-dono", "destino-real-sem-apd-ref"}),
    "r_alertas": frozenset(
        {
            "severidade-invalida",
            "runbook-inexistente",
            "limite-do-wal-divergente",
            "alerta-sem-razao",
            "falta-desactualizada",
            "alertas-do-ticket-em-falta",
        }
    ),
    "r_segredos_no_inventario": frozenset({"segredo-fora-do-inventario"}),
    "r_restauro": frozenset(
        {"periodo-invalido", "agendador-sem-estado", "agendador-sem-credor"}
    ),
}

#: O que se copia: so o que o `varrer` le. Copiar a arvore toda levava segundos
#: por caso e nao acrescentava nada.
_A_COPIAR_FICHEIROS = (
    lint.COBERTURA,
    lint.PGBACKREST,
    lint.ARQUIVO,
    lint.CATALOGO,
    lint.INVENTARIO_DE_SEGREDOS,
)
_A_COPIAR_PASTAS = (lint.RUNBOOKS,)


def _copiar(origem: Path, destino: Path) -> None:
    for relativo in _A_COPIAR_FICHEIROS:
        alvo = destino / relativo
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem / relativo, alvo)
    for relativo in _A_COPIAR_PASTAS:
        shutil.copytree(origem / relativo, destino / relativo)


def correr(raiz: Path) -> tuple[list[str], dict[str, int]]:
    """Corre todos os casos. Devolve `(falhas, numeros)`."""
    falhas: list[str] = []
    exercitadas: set[str] = set()

    # A linha de base: a arvore real tem de estar limpa. Sem isto, um caso que
    # «da vermelho» podia estar a dar vermelho pelo que ja la estava.
    base, _ = lint.varrer(raiz)
    if base:
        return (
            [
                "a arvore real nao esta limpa, e o canario compara com ela: "
                + "; ".join(str(a) for a in base[:5])
            ],
            {
                "casos": len(CASOS),
                "morderam": 0,
                "regras_exercitadas": 0,
                "regras": len(lint.REGRAS),
            },
        )

    mordidos = 0
    for caso in CASOS:
        with tempfile.TemporaryDirectory(prefix="backup-lint-canario-") as pasta:
            destino = Path(pasta)
            _copiar(raiz, destino)
            copia = Copia(destino)
            try:
                caso.mutacao(copia)
            except NaoSeAplica as erro:
                falhas.append(
                    f"[{caso.codigo}] a mutacao nao se aplica ({erro}). Uma "
                    "mutacao que deixou de mudar nada e uma prova que deixou de "
                    "existir."
                )
                continue
            try:
                achados, _ = lint.varrer(destino)
            except lint.ConfiguracaoInvalida as erro:
                # Saida 2 tambem e morder, e **nao** e o que o caso declarou: um
                # ficheiro ilegivel esconde a regra que se queria provar.
                falhas.append(
                    f"[{caso.codigo}] a mutacao tornou a configuracao ilegivel "
                    f"({erro}); esperavam-se {sorted(caso.espera)}"
                )
                continue
            regras = {a.regra for a in achados}
            exercitadas |= regras & caso.espera
            em_falta = caso.espera - regras
            a_mais = regras - caso.espera - caso.tolera
            if em_falta:
                falhas.append(
                    f"[{caso.codigo}] {caso.descricao}: nao disparou "
                    f"{sorted(em_falta)} (disparou {sorted(regras) or 'nada'})"
                )
            if a_mais:
                falhas.append(
                    f"[{caso.codigo}] {caso.descricao}: disparou tambem "
                    f"{sorted(a_mais)}, que o caso nao declarou. Ser apanhado "
                    "por outra regra e sorte, nao cobertura."
                )
            if not em_falta and not a_mais:
                mordidos += 1

    # O terceiro fecho: nenhuma regra sem canario.
    nomes = {regra.__name__ for regra in lint.REGRAS}
    for nome in sorted(nomes - set(MINIMO_POR_REGRA)):
        falhas.append(
            f"a regra `{nome}` nao esta em MINIMO_POR_REGRA: uma regra nova sem "
            "canario fica em silencio."
        )
    for nome in sorted(set(MINIMO_POR_REGRA) - nomes):
        falhas.append(
            f"`{nome}` esta em MINIMO_POR_REGRA e nao e uma regra de lint.REGRAS."
        )
    for nome, codigos in sorted(MINIMO_POR_REGRA.items()):
        if nome not in nomes:
            continue
        nao_provados = codigos - exercitadas
        if nao_provados:
            falhas.append(
                f"a regra `{nome}` tem os achados {sorted(nao_provados)} sem "
                "nenhum caso a prova-los."
            )

    return falhas, {
        "casos": len(CASOS),
        "morderam": mordidos,
        "regras_exercitadas": len(
            {nome for nome, codigos in MINIMO_POR_REGRA.items() if codigos & exercitadas}
        ),
        "regras": len(lint.REGRAS),
    }
