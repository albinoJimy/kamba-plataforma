"""Gates de base de dados: 8 (migracoes) e 6 (isolamento de tenant).

    python db/gate_bd.py --suite tests               # gate 8
    python db/gate_bd.py --suite tests_identidade    # gate 8, segunda metade
    python db/gate_bd.py --suite tests_isolamento    # gate 6
    python db/gate_bd.py --suite tests_chr           # gate 8, o CHR (KAM-014)
    python db/gate_bd.py --suite tests_outbound      # gate 8, a saida (KAM-015)
    python db/gate_bd.py --suite tests_handoff       # gate 8, o handoff (KAM-019)
    python db/gate_bd.py --suite tests_media         # gate 8, a midia (KAM-020)
    python db/gate_bd.py --suite tests_modos         # gate 8, os modos (KAM-018)
    python db/gate_bd.py --suite tests_avisos        # gate 8, o aviso ao dono (KAM-115)
    python db/gate_bd.py --suite tests_agr           # gate 8, o AGR (KAM-025)
    python db/gate_bd.py --suite tests_pagamentos    # gate 8, o ledger (KAM-053)
    python db/gate_bd.py --suite tests_dimensionamento  # ensaio de carga (KAM-084), fora do CI
    python db/gate_bd.py --suite tests --bd-existente

Os dois gates precisam do mesmo: um PostgreSQL real, vazio e descartavel. Este
ficheiro levanta-o e corre a suite pedida; o que cada gate prova esta nas
suites (`db/tests/`, `db/tests_identidade/` e `db/tests_isolamento/`). A base
chama-se `kamba_gate8` em todos os casos — o nome e o do trinco, e ficou do
primeiro gate que o usou.

`tests_identidade` (KAM-008) corre o modulo de identidade — TypeScript, em
`packages/core-ts` — contra a base, e precisa de saber em que contentor ela
esta, para lhe pedir o `pg_dump` e o registo do servidor: o nome vai em
`KAMBA_GATE_CONTENTOR`.

O gate precisa de um PostgreSQL **real** e **vazio**, e nao pode ser o de
desenvolvimento: a suite faz `downgrade base`, que apaga o schema `platform`.
Por isso o caminho por omissao levanta o seu proprio contentor:

- a mesma imagem do compose, **fixada por digest** — o criterio de aceitacao diz
  PostgreSQL 18.6, e uma etiqueta que flutue de *minor* deixava de o provar;
- dados em `tmpfs`: nada toca no disco e nada sobrevive;
- porta publicada so em `127.0.0.1`, escolhida pelo Docker;
- palavras-passe geradas nesta execucao: passam ao contentor e a suite pelo
  ambiente, nao pela linha de comandos, e nao se imprimem. (Ficam visiveis no
  `docker inspect` do contentor enquanto ele vive, como qualquer variavel de
  ambiente de um contentor; sao efemeras e a porta so escuta em 127.0.0.1.)

O contentor e removido no fim, corra a suite bem ou mal, e tambem quando o
processo recebe SIGINT ou SIGTERM. **Nao** quando e morto com SIGKILL: nesse
caso fica um `kamba-gate8-*` orfao, que se remove a mao.

`--bd-existente` existe para quando o Docker nao esta ao alcance do processo
(por exemplo, a correr ja dentro de um contentor, com a base noutro). Tem dois
trincos, e o segundo e o que importa:

- a base tem de se chamar `kamba_gate8`;
- as palavras-passe dos oito papeis tem de vir **dadas** no ambiente. Os papeis
  sao globais a instancia, nao a base: o `bootstrap` redefine-lhes a
  palavra-passe, e gera-las aqui trocava as credenciais de todos os servicos da
  instancia por valores que ninguem conhece. Este modo so e seguro contra uma
  instancia descartavel; o trinco do nome protege a base, nao a instancia.
"""

from __future__ import annotations

import argparse
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

DB = Path(__file__).resolve().parent
sys.path.insert(0, str(DB))

# O digest da fila vive em `db/fila_do_gate.py`, e nao aqui: o
# `ci/supply-chain/imagens.yaml` aceita **uma** constante por ficheiro em
# `fontes_adicionais`, e este ja la esta com a `IMAGEM` do PostgreSQL.
import fila_do_gate  # noqa: E402

#: A imagem do compose de desenvolvimento, com o digest observado e registado
#: em `docs/evidencia/KAM-001-node.md` §3 (PostgreSQL 18.6, pgvector 0.8.7).
#: Desde o KAM-067 a fixacao e sistematica: esta constante esta declarada em
#: `ci/supply-chain/imagens.yaml` (`fontes_adicionais`), e `make supply-chain`
#: falha se o digest daqui deixar de ser o do inventario.
IMAGEM = (
    "pgvector/pgvector:0.8.7-pg18"
    "@sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11"
)

BASE = "kamba_gate8"
ADMIN = "kamba"
ESPERA_MAXIMA = 90
#: Segundos. Num runner Linux a suite corre em poucos minutos; isto e folga
#: para uma maquina lenta ou partilhada (medido em Windows com Docker Desktop:
#: perto de dez minutos na suite `tests` antes de se poupar o Alembic em
#: `tests/base.py`), nao alvo.
TEMPO_MAXIMO_DA_SUITE = 900
#: As suites com fila levam mais: o criterio 4 para a fila 60 s de proposito e
#: o criterio 8 mede 5 minutos de carga. Sao tempos do **criterio**, nao folga.
TEMPO_MAXIMO_DOS_EVENTOS = 1500
#: As suites que este ficheiro sabe correr. Lista fechada.
SUITES = (
    "tests",
    "tests_identidade",
    "tests_isolamento",
    "tests_eventos",
    "tests_eventos_consumo",
    "tests_eventos_carga",
    # KAM-012: as mil insercoes concorrentes do criterio 3. Suite propria pela
    # mesma razao que a carga de eventos — custa minutos, e uma suite custa
    # isso por cada mutacao que a escolha.
    "tests_auditoria_carga",
    # KAM-009: a regra de consumo de limites (`platform.ten_consumir`) — as mil
    # chamadas paralelas do criterio 3, a idempotencia, a fronteira de mes com
    # relogio fixo e o isolamento da funcao. Suite propria e nao dentro de
    # `tests` pela mesma razao das duas acima: as mil paralelas custam, e cada
    # mutacao da revisao 0007 pagaria esse custo somado ao da suite inteira.
    "tests_ten",
    # KAM-013: a entrada de canal. Precisa de PostgreSQL **e** de fila, e corre
    # os processos de producao — `services/gwy/src/server.ts` e
    # `services/worker-canal/src/entrada.ts` — em vez de um programa de ensaio.
    # Suite propria e nao dentro de `tests` por duas razoes: levanta e para
    # processos HTTP, o que `tests` nao faz; e para a fila a meio, o que
    # deixaria as outras 387 asercoes a correr contra um Redis em baixo.
    "tests_entrada",
    # KAM-013: o perfil de carga do criterio 7 — 200 pedidos/s durante 60 s.
    # Suite propria pela mesma razao da carga de eventos: custa um minuto de
    # relogio, e cada mutacao que a escolhesse pagaria esse custo.
    "tests_entrada_carga",
    # KAM-014: o CHR. Corre o modulo TypeScript (`packages/core-ts/src/chr/`)
    # contra a base, com os **tres papeis verdadeiros** — `kamba_resolver`,
    # `kamba_identity` e `kamba_app` —, que e a unica forma de provar que o
    # `phone_number_id` de A nao devolve o contexto de B e que `kamba_app`
    # sozinho nao responde a pergunta. Nao precisa de fila: a porta do AGR e
    # uma interface, e o que ela faz com o *job* e KAM-025.
    "tests_chr",
    # KAM-015: a saida de canal. Corre o modulo TypeScript
    # (`packages/core-ts/src/outbound/`) contra a base **e** contra o servidor
    # Graph falso do KAM-024, que e a unica forma de provar as tres coisas que
    # nao se simulam: que duas chamadas com a mesma chave dao **uma** linha (a
    # unicidade e da base, nao do codigo), que um `delivered` seguido de um
    # `sent` fica `delivered` (a monotonia tem de sobreviver a concorrencia
    # real), e que o `pricing` de um estado fica guardado por mensagem. Nao
    # precisa de fila: a ordem por conversa prova-se com o registo do servidor
    # falso, e a fila de saida e do proprio adapter.
    "tests_outbound",
    # KAM-019: a passagem a humano. O que so aqui se prova, e nao se simula
    # contra uma base falsa: que cinco aberturas concorrentes deixam **uma**
    # linha (a idempotencia e da chave primaria derivada, nao do codigo), que a
    # mesma conta do provedor em dois tenants e **recusada pela base** (o furo
    # que o X-10 procura, e que a chave primaria sozinha nao fecha), que dois
    # `close` em paralelo escrevem uma vez so, e que a RLS esconde a passagem de
    # A do contexto de B. **Nao leva o `tools/meta-sim`** e nao precisa de fila:
    # o handoff nao fala com a Meta, e o provedor de atendimento entra por porta.
    "tests_handoff",
    # KAM-020: a midia recebida. O que so aqui se prova e o que a base falsa das
    # baterias do gate 4 **nunca** poderia provar, porque ela nao le o texto do
    # SQL: que o `ON CONFLICT` da reserva funciona sob concorrencia (duas
    # chamadas em duas ligacoes, que e a unica forma de o provocar — em serie a
    # segunda nem chega ao `INSERT`), que o `WHERE estado = 'pendente'` impede
    # uma segunda marcacao de reescrever um `armazenado`, que a
    # `media_assets_armazenado_ck` recusa quando o caminho e o do codigo, e o
    # X-03 sobre a tabela nova. **Nao leva o `tools/meta-sim`** e nao precisa de
    # fila: a midia fala com a Meta por **porta**, e a razao de ser porta e que
    # a API de midia dela nao tem evidencia nenhuma no `E1` — um simulador
    # seria uma invencao a fingir medicao.
    "tests_media",
    # KAM-018: os modos da conversa e o silenciamento do bot. O que so aqui se
    # prova e o que **nenhuma** base falsa pode provar, porque o objecto da prova
    # e o servidor: que o `pg_advisory_xact_lock(hash(tenant_id, contact_id))` e
    # exclusao mutua a serio — a guarda **bloqueia** a porta de uma transicao em
    # curso e, quando entra, ve o modo mudado —, que duas transicoes concorrentes
    # em duas ligacoes deixam **uma** transicao e **um** evento (o predicado
    # `mode = ANY(...)` e quem decide, nao quem leu primeiro), que as 100
    # intercalacoes do criterio 3 dao 0 mensagens do bot depois de o *echo* estar
    # registado, que o relogio das 24 h conta do `handoffs.opened_at` quando nao
    # houve actividade humana (um `COALESCE` com subconsulta e um `max`, que so
    # um planeador resolve), e que o `GRANT UPDATE (mode, last_human_activity_at)`
    # da revisao `0016` existe — e e **por coluna**, com as quatro da identidade
    # da conversa ainda vedadas. **Nao leva o `tools/meta-sim`** e nao precisa de
    # fila: a guarda recusa o envio **antes** de haver chamada a Meta, e a porta
    # do AGR e uma interface (KAM-025).
    "tests_modos",
    # KAM-115: o aviso ao dono por canal alternativo. O que so aqui se prova e o
    # que o objecto da prova obriga — o servidor: que as onze cadeias de
    # `src/avisos/consultas.ts` **correm** (uma base falsa compara-as por texto
    # e nunca as interpreta, pelo que um erro de sintaxe passava o gate 4
    # inteiro e falhava no primeiro aviso real), que o `ON CONFLICT DO NOTHING`
    # da idempotencia do criterio 2 desempata entre **duas** ligacoes e nao por
    # quem leu primeiro, que o `owner_notices_lembrete_ck` recusa o quarto
    # lembrete do criterio 4, que a confirmacao do criterio 6 e **atomica** — a
    # comparacao do resumo e o prazo estao na instrucao, e com a leitura e a
    # escrita separadas passavam duas confirmacoes do mesmo *token* —, que as
    # tres varreduras correm com `BYPASSRLS` e **nao** correm como `kamba_app`,
    # que o endereco do dono nao aparece em claro em coluna nenhuma, e o X-03
    # sobre as duas tabelas novas. **Nao leva o `tools/meta-sim`** e nao precisa
    # de fila: este modulo nao fala com a Meta — e o ticket inteiro, porque
    # avisar o dono pelo canal que falhou e inutil — e os notificadores sao
    # portas, que o criterio 3 manda exercitar com fornecedor falso.
    "tests_avisos",
    # KAM-025: o AGR. Python puro, e o que so aqui se prova e o que o objecto
    # da prova obriga — o servidor: que o `pg_advisory_lock` de **sessao** e
    # exclusao mutua entre sessoes (com uma ligacao nao ha forma de o medir: a
    # segunda tomada na mesma sessao e concedida de imediato), que a tranca
    # larga quando a ligacao **morre** (um `SIGKILL` a serio num processo filho,
    # que e o criterio 4 e o que dispensa um temporizador), que a chave desta
    # tranca **colide** com a do `pg_advisory_xact_lock` dos modos (KAM-018) —
    # uma afirmacao sobre o `hashtextextended` que so a base confirma —, que as
    # quatro cadeias de `src/kamba_agr/consultas.py` **correm** (uma base falsa
    # compara-as por texto e nunca as interpreta), e que a RLS esconde a
    # conversa de A do contexto de B (X-02) incluindo no `EXISTS` sobre
    # `handoffs`. Nao precisa de fila: o consumidor e um shim em TypeScript
    # (ADR-L004) e a porta do AGR e HTTP.
    "tests_agr",
    # KAM-047: a agenda da vertical Servicos. As **mil tentativas paralelas** do
    # criterio 1 no mesmo recurso e intervalo, mais a expiracao de holds, a
    # remarcacao atomica, os limites e o isolamento por contacto. Suite propria
    # e nao dentro de `tests`, pela mesma razao do `tests_ten` e do
    # `tests_auditoria_carga`: as mil custam relogio, e uma suite paga isso por
    # cada mutacao que a escolha.
    "tests_servicos",
    # KAM-043: o preco opaco e o stock nao-garantido. O que so aqui se prova
    # e o que uma base falsa nao pode provar, porque o objecto da prova e o
    # motor: que o `offer_terms_preco_ck` do criterio 1 **recusa** as duas
    # metades da equivalencia (um `sob_consulta` com numero e um `fixo` sem
    # ele), que a RLS `FORCE` esconde a oferta de A do contexto de B e falha
    # fechada sem contexto (ISO-39..42 na forma das tabelas novas), que a
    # chave composta `(tenant_id, sku)` faz da colisao de SKU entre tenants um
    # nao-problema (ISO-33..38), que a FK composta do contacto **recusa** uma
    # cotacao de A sobre um contacto de B — a simples aceita-a, e esta medido
    # (ISO-58) —, e que as cadeias de
    # `services/com/src/produtos/consultas.ts` **correm**: a suite le-as do
    # proprio ficheiro TypeScript, pelo que o que o gate exercita e o texto
    # que o modulo envia e nao uma copia dele.
    "tests_produtos",
    # KAM-053: o ledger de pagamentos. O que so aqui se prova e o que o objecto
    # da prova obriga — o servidor, e nao um duplo: que um `INSERT` directo em
    # `payment_events` falha por **privilegio** (`42501`) antes de chegar a
    # qualquer `CHECK`, que o `deny_mutation` recusa um `UPDATE` **ao
    # superutilizador** (o unico que os `REVOKE` nao prendem, e nenhuma matriz
    # de privilegios o consegue), que as **vinte** sessoes concorrentes do
    # criterio 3 dao sequencias 1..20 sem lacunas — em serie o `1 + count(*)` da
    # sempre o numero certo e o ensaio ficava verde sem `FOR UPDATE` nenhum, e e
    # por isso que ha um passo de canario que troca o `FOR UPDATE` por um
    # `SELECT` simples numa copia da funcao e exige que elas colidam —, que a
    # `append_payment_event` corre `SECURITY DEFINER` e **nao** contorna o
    # `FORCE` (a afirmacao central do `db/rls.py`, que nomeia este ticket como
    # credor: com o contexto de B sobre uma cobranca de A, a porta recusa), que
    # uma falha forcada no `evt_emitir` reverte tambem a linha do ledger — a
    # guarda de PII da `0004`, e nao um duplo, porque uma falha injectada provava
    # que a injeccao funciona —, e que um byte alterado com superutilizador faz o
    # `verify_ledger_chain` apontar o elo. Mais a propriedade do criterio 5: mil
    # sequencias validas aleatorias em que o `rebuild_charge_state` da o mesmo
    # que a projeccao.
    #
    # Suite propria e nao dentro de `tests`, pela razao do `tests_ten`, do
    # `tests_servicos` e do `tests_produtos`: as vinte concorrentes e as mil
    # sequencias custam relogio, e uma suite paga isso por cada mutacao que a
    # escolha. **Nao** precisa de fila: o *outbox* escreve-se na transaccao, e
    # quem o publica e o KAM-005.
    "tests_pagamentos",
    # KAM-044: as encomendas. O que so aqui se prova, e nenhuma base falsa
    # pode, porque o objecto da prova e o motor: que o *trigger*
    # `BEFORE UPDATE` recusa **78 dos 88** pares medidos por execucao — os
    # outros 56 dos 144 sao os 8 `X -> X` (que nao sao transicoes) e os 48
    # dos quatro estados do KAM-050, inalcancaveis por construcao; a
    # primeira versao desta nota dizia «cento e vinte» e a revisao
    # adversarial contou 67 (com o canario que o desliga e exige que a transicao
    # invalida passe, sem o qual o ensaio nao distingue o *trigger* de um
    # `CHECK` de dominio); que vinte transicoes concorrentes sobre a mesma
    # versao deixam **uma** a escrever e dezanove a reler, com o canario que
    # tira o `version = $3` e exige que ganhem mais do que uma; que o
    # `CONSTRAINT TRIGGER` **diferido** recusa no `COMMIT` uma mudanca de
    # estado sem registo e um `paga` sem evento autenticado do PAY — a
    # barreira do criterio 3, que uma verificacao em TypeScript so cobre pela
    # via do TypeScript; que o `deny_mutation` recusa `UPDATE`, `DELETE` e
    # `TRUNCATE` no registo **ao superutilizador**; que o gerador do
    # `numero_publico` da dez mil valores distintos (com oito caracteres e nao
    # seis, e a conta esta no ensaio); e que uma falha injectada depois da
    # emissao reverte **as duas** escritas, porque o `evt_emitir` corre na
    # transaccao de quem chama.
    "tests_encomendas",
    # KAM-084: o ensaio de carga do segmento de entrada (S1, S2, rajada e
    # rampa), com duas replicas do GWY e o *worker* de entrada de producao.
    # **Nao corre no CI**: nao esta no `ci-8` do `Makefile`, e de proposito — e
    # meia hora de relogio e uma medicao de dimensionamento, nao um portao. Por-la
    # num gate e decisao do fundador.
    "tests_dimensionamento",
)
#: As que precisam tambem de uma fila.
SUITES_COM_FILA = (
    "tests_eventos",
    "tests_eventos_consumo",
    "tests_eventos_carga",
    "tests_entrada",
    "tests_entrada_carga",
    "tests_dimensionamento",
)

#: KAM-084: os cinco cenarios do ensaio de carga levam ~30 min com a drenagem.
#: Tempo do **criterio** (300 s por cenario, a rajada de uma hora a 20x), e nao
#: folga.
TEMPO_MAXIMO_DA_CARGA = 3600


def _docker(*argumentos: str, ambiente=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *argumentos], capture_output=True, text=True, env=ambiente
    )


def _ambiente_da_suite(host: str, porta: str, senha_admin: str) -> dict[str, str]:
    ambiente = dict(os.environ)
    ambiente.update(
        {
            "KAMBA_DB_HOST": host,
            "KAMBA_DB_PORT": porta,
            "KAMBA_DB_NAME": BASE,
            "POSTGRES_USER": ADMIN,
            "POSTGRES_PASSWORD": senha_admin,
            "KAMBA_SECRET_DB_MIGRATOR_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_APP_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_BATCH_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_RESOLVER_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_IDENTITY_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_AUDIT_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_AGR_PASSWORD": secrets.token_urlsafe(24),
            # KAM-053: o papel estreito dos callbacks de pagamento.
            "KAMBA_SECRET_DB_PAY_HOOKS_PASSWORD": secrets.token_urlsafe(24),
        }
    )
    return ambiente


def _esperar_pela_base(ambiente: dict[str, str]) -> None:
    """Espera ate a base aceitar ligacoes autenticadas.

    Nao basta o `pg_isready`: o entrypoint da imagem arranca o servidor uma
    primeira vez para o `initdb` e reinicia-o. Uma ligacao real, repetida, e a
    unica prova de que o que responde ja e o servidor definitivo.
    """
    sys.path.insert(0, str(DB))
    import ligacao

    limite = time.monotonic() + ESPERA_MAXIMA
    ultimo: Exception | None = None
    estaveis = 0
    while time.monotonic() < limite:
        try:
            conexao = ligacao.ligar("admin", ambiente)
            conexao.close()
            estaveis += 1
            if estaveis >= 3:
                return
        except Exception as erro:  # noqa: BLE001 — qualquer falha e «ainda nao»
            ultimo = erro
            estaveis = 0
        time.sleep(1)
    raise RuntimeError(
        f"a base nao ficou disponivel em {ESPERA_MAXIMA}s: {type(ultimo).__name__}"
    )


def _correr_suite(ambiente: dict[str, str], suite: str) -> int:
    # Pelo `correr_suite.py` e nao por `python -m unittest`: este sai com 0
    # quando todos os testes sao saltados, e o trinco da suite salta. Num gate,
    # saltar e falhar.
    limite = (
        TEMPO_MAXIMO_DA_CARGA
        if suite == "tests_dimensionamento"
        else TEMPO_MAXIMO_DOS_EVENTOS
        if suite in SUITES_COM_FILA
        else TEMPO_MAXIMO_DA_SUITE
    )
    try:
        return subprocess.run(
            [sys.executable, "correr_suite.py", suite],
            cwd=DB,
            env=ambiente,
            timeout=limite,
        ).returncode
    except subprocess.TimeoutExpired:
        # Um gate pendurado e pior do que um gate vermelho: ocupa o runner ate
        # ao limite do job e nao diz porque. Passar da folga e um bloqueio, e
        # diz-se.
        print(
            f"gate de BD: a suite nao terminou em {limite}s. "
            "Provavelmente um bloqueio entre ligacoes (um teste a fazer DDL com "
            "outra transaccao aberta).",
            file=sys.stderr,
        )
        return 1


def com_contentor(suite: str) -> int:
    senha_admin = secrets.token_urlsafe(24)
    sufixo = secrets.token_hex(4)
    nome = f"kamba-gate8-{sufixo}"
    com_fila = suite in SUITES_COM_FILA
    # A rede so se cria quando faz falta: o caminho das outras tres suites fica
    # exactamente como estava.
    rede = f"kamba-eventos-{sufixo}" if com_fila else ""
    ambiente_docker = dict(os.environ)
    ambiente_docker.update(
        {"POSTGRES_USER": ADMIN, "POSTGRES_PASSWORD": senha_admin, "POSTGRES_DB": BASE}
    )
    if com_fila:
        criacao = _docker("network", "create", rede)
        if criacao.returncode != 0:
            print(f"gate de BD: nao foi possivel criar a rede:\n{criacao.stderr}",
                  file=sys.stderr)
            return 2
    arranque = _docker(
        "run", "--detach", "--rm", "--name", nome,
        # Sem valor: o Docker le-as do ambiente deste processo, pelo que a
        # palavra-passe nao aparece na linha de comandos (nem em `ps`).
        "--env", "POSTGRES_USER", "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_DB",
        "--env", "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256",
        "--tmpfs", "/var/lib/postgresql",
        "--publish", "127.0.0.1::5432",
        *(("--network", rede) if com_fila else ()),
        IMAGEM,
        ambiente=ambiente_docker,
    )
    if arranque.returncode != 0:
        print(f"gate de BD: nao foi possivel arrancar o PostgreSQL:\n{arranque.stderr}",
              file=sys.stderr)
        if com_fila:
            _docker("network", "rm", rede)
        return 2
    fila = ""
    try:
        porta = _docker("port", nome, "5432/tcp").stdout.strip().rsplit(":", 1)[-1]
        if not porta.isdigit():
            print("gate de BD: o Docker nao devolveu a porta publicada", file=sys.stderr)
            return 2
        ambiente = _ambiente_da_suite("127.0.0.1", porta, senha_admin)
        # Para a suite de identidade: e pelo contentor que se pede o `pg_dump`
        # e o registo do servidor.
        ambiente["KAMBA_GATE_CONTENTOR"] = nome
        if com_fila:
            fila = f"kamba-fila-{sufixo}"
            porta_da_fila = fila_do_gate.arrancar(rede, fila)
            ambiente.update(
                {
                    "KAMBA_GATE_FILA": fila,
                    "KAMBA_GATE_REDE": rede,
                    "KAMBA_FILA_HOST": "127.0.0.1",
                    "KAMBA_FILA_PORT": porta_da_fila,
                    # O publicador corre em Node, dentro da rede: chega a base e
                    # a fila pelo nome do contentor, nao pela porta publicada.
                    "KAMBA_QUEUE_URL": f"redis://{fila}:6379",
                    "KAMBA_DB_HOST_NA_REDE": nome,
                }
            )
        _esperar_pela_base(ambiente)
        return _correr_suite(ambiente, suite)
    except RuntimeError as erro:
        print(f"gate de BD: {erro}", file=sys.stderr)
        registo = _docker("logs", "--tail", "20", nome)
        print(registo.stdout + registo.stderr, file=sys.stderr)
        return 2
    finally:
        if fila:
            _docker("rm", "--force", fila)
        _docker("rm", "--force", nome)
        if com_fila:
            _docker("network", "rm", rede)


def com_bd_existente(suite: str) -> int:
    if os.environ.get("KAMBA_DB_NAME", "") != BASE:
        print(
            f"gate de BD: --bd-existente exige KAMBA_DB_NAME={BASE}. O gate apaga o "
            "schema `platform` e so corre contra a base descartavel.",
            file=sys.stderr,
        )
        return 2
    ambiente = dict(os.environ)
    em_falta = [
        f"KAMBA_SECRET_DB_{papel}_PASSWORD"
        for papel in (
            "MIGRATOR",
            "APP",
            "BATCH",
            "RESOLVER",
            "IDENTITY",
            "AUDIT",
            "AGR",
            "PAY_HOOKS",
        )
        if not ambiente.get(f"KAMBA_SECRET_DB_{papel}_PASSWORD")
    ]
    if em_falta:
        print(
            "gate de BD: --bd-existente exige as palavras-passe dos oito papeis no "
            f"ambiente; faltam: {', '.join(em_falta)}.\n"
            "    Os papeis sao globais a instancia: gera-las aqui trocava as "
            "credenciais de todos os servicos que a usam.",
            file=sys.stderr,
        )
        return 2
    try:
        _esperar_pela_base(ambiente)
    except RuntimeError as erro:
        print(f"gate de BD: {erro}", file=sys.stderr)
        return 2
    return _correr_suite(ambiente, suite)


def _sair_com_limpeza(numero, _quadro) -> None:
    """SIGINT/SIGTERM passam a excepcao, para os `finally` correrem."""
    raise SystemExit(128 + numero)


def main(argv: list[str] | None = None) -> int:
    for sinal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sinal, _sair_com_limpeza)
    analisador = argparse.ArgumentParser(prog="gate_bd", description=__doc__.split("\n")[0])
    analisador.add_argument(
        "--suite",
        choices=SUITES,
        default="tests",
        help="tests e tests_identidade (gate 8) ou tests_isolamento (gate 6)",
    )
    analisador.add_argument(
        "--bd-existente",
        action="store_true",
        help=f"usa a base apontada pelo ambiente (tem de se chamar {BASE})",
    )
    argumentos = analisador.parse_args(argv)
    if argumentos.bd_existente:
        return com_bd_existente(argumentos.suite)
    return com_contentor(argumentos.suite)


if __name__ == "__main__":
    sys.exit(main())
