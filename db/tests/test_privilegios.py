"""Gate 8: o que cada papel **consegue**, e nao so os atributos que tem.

A primeira versao destes testes media `rolbypassrls` e pouco mais, e a revisao
adversarial mostrou o que isso deixava passar: com `GRANT kamba_batch TO
kamba_app` no bootstrap — a aplicacao a um `SET ROLE` de contornar a RLS — os
75 testes continuavam verdes. O criterio «`kamba_app` `NOBYPASSRLS`, sem DDL»
passava com a propriedade falsa.

Aqui mede-se o efeito: pertencas, a matriz exacta de privilegios por tabela e
por coluna, os privilegios por omissao, e o que acontece quando `kamba_app`
tenta o que nao deve.
"""

from __future__ import annotations

import bootstrap
import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    TABELAS,
    TABELAS_0001,
    VIOLACAO_DE_CHECK,
    ComBase,
)

PRIVILEGIOS_DE_TABELA = (
    "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER",
)

#: O que cada papel tem **ao nivel da tabela** nas tres tabelas da revisao 0001.
#: `kamba_app` nao tem UPDATE de tabela: tem-no coluna a coluna (ver abaixo).
#: `kamba_resolver` nao tem **nada** ao nivel da tabela: so `SELECT` por coluna
#: (conferido em `tests_isolamento/test_resolver.py`). Esteve fora desta matriz,
#: e a revisao do KAM-004 mostrou que um `GRANT INSERT` ao resolvedor passava
#: nos dois gates. `kamba_migrator` e o dono, e tem tudo. `kamba_identity`
#: (KAM-008) nao tem nada nestas tres: nao le tenants, canais nem entitlements.
_ESPERADO_0001 = {
    "kamba_app": {"SELECT", "INSERT"},
    "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "kamba_resolver": set(),
    "kamba_identity": set(),
    # O papel de auditoria (KAM-012) le **o registo de auditoria** e mais nada.
    # Quem audita um preco le a linha de `audit_log`, que ja tem o antes e o
    # depois em hash; nao precisa da tabela de onde o preco veio, e dar-lha
    # fazia dele um segundo papel de leitura geral.
    "kamba_audit": set(),
    "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
    "public": set(),
}


def _identidade(*privilegios: str) -> dict[str, set[str]]:
    """Matriz de uma tabela da revisao 0003: so `kamba_identity` e o dono.

    `kamba_app` nao tem **nada** ao nivel da tabela — em `contacts` tem `SELECT`
    por coluna (ver `COLUNAS_POR_PAPEL`), nas outras nem isso. `kamba_batch`
    tambem nao: quem purga (KAM-071) e quem roda chaves (KAM-072) pede o que
    precisar por revisao, em vez de herdar `BYPASSRLS` sobre o cofre.
    """
    return {
        "kamba_app": set(),
        "kamba_batch": set(),
        "kamba_resolver": set(),
        "kamba_identity": set(privilegios),
        "kamba_audit": set(),
        "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
        "public": set(),
    }


#: `entitlements` deixou de ser igual as outras duas da `0001` com o KAM-009.
#:
#: A revisao `0007` revoga a `kamba_app` o `INSERT` **e** o `UPDATE`, e o
#: `INSERT` foi um critico da revisao adversarial: a primeira versao revogava
#: so o `UPDATE`, e com `WITH CHECK (tenant_id = app.tenant_id)` um tenant
#: **inseria a propria linha** com o tecto que quisesse. Nao e preciso subir o
#: proprio tecto se se pode criar um — e a regra do minimo entre modulos nao
#: protege nada quando a linha nova e a unica que declara a chave.
#:
#: A aplicacao **le** entitlements (o `checkEntitlement` do criterio 2) e
#: consome contra eles pela `ten_consumir`. Escrever e de retaguarda: KAM-091
#: provisiona, KAM-059 cobra.
_ESPERADO_ENTITLEMENTS = dict(_ESPERADO_0001, kamba_app={"SELECT"})

#: tabela -> papel -> privilegios de tabela. Cobre **todas** as tabelas de
#: `platform`: uma tabela nova sem linha aqui falha `test_a_matriz_cobre_...`.
ESPERADO_POR_TABELA = {tabela: _ESPERADO_0001 for tabela in TABELAS_0001}
ESPERADO_POR_TABELA.update(
    {
        "entitlements": _ESPERADO_ENTITLEMENTS,
        "contacts": _identidade("SELECT", "INSERT"),
        "contact_deks": _identidade("SELECT", "INSERT"),
        # O unico `DELETE` fora do `kamba_batch`: o apagamento a pedido do
        # titular e um `DELETE` verdadeiro (doc 06 §7.6), e so aqui.
        "contact_endpoints": _identidade("SELECT", "INSERT", "DELETE"),
        "hmac_key_versions": _identidade("SELECT", "INSERT"),
    }
)



def _uso(**por_papel: set[str]) -> dict[str, set[str]]:
    """Matriz de uma tabela da revisao 0007 (KAM-009).

    O dono tem tudo; o `kamba_batch` tambem, porque e quem purga um periodo
    fechado; `kamba_resolver`, `kamba_identity` e `kamba_audit` **nada** — o
    resolvedor corre antes de haver contexto, a identidade nao sabe de
    limites, e quem audita le o `audit_log` e nao os contadores.
    """
    base = {
        "kamba_app": set(),
        # Os quatro de dados, e nao `PRIVILEGIOS_DE_TABELA` inteiro: o
        # `TRUNCATE` esvazia uma tabela sem passar por RLS nem por trigger, o
        # `REFERENCES` deixa criar FK para ela, e o `TRIGGER` deixa pendurar
        # codigo que corre em cada escrita. Nenhum dos tres e preciso para
        # purgar um periodo fechado, e o `kamba_batch` tem exactamente estes
        # quatro em todas as outras tabelas desde a `0001`.
        "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        "kamba_resolver": set(),
        "kamba_identity": set(),
        "kamba_audit": set(),
        "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
        "public": set(),
    }
    base.update(por_papel)
    return base


def _auditoria(**por_papel: set[str]) -> dict[str, set[str]]:
    """Matriz de uma tabela da revisao 0006 (KAM-012).

    O dono tem tudo — **e nem assim altera ou apaga**: o privilegio e de
    tabela, e o que o impede e o *trigger* `ENABLE ALWAYS`, que esta bateria
    nao ve. O `test_auditoria.py` e que o prova.
    """
    base = {
        "kamba_app": set(),
        "kamba_batch": set(),
        "kamba_resolver": set(),
        "kamba_identity": set(),
        "kamba_audit": set(),
        "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
        "public": set(),
    }
    base.update(por_papel)
    return base


ESPERADO_POR_TABELA.update(
    {
        # **Quem escreve nao le.** O criterio 8 do KAM-012 pede que a leitura
        # do registo seja recusada ao papel da aplicacao, e e por isso que o
        # `kamba_app` tem `INSERT` e nao tem `SELECT`. O `kamba_batch` escreve
        # as accoes de plataforma e le a cadeia inteira para a verificar de
        # noite. O `kamba_audit` so le. **Ninguem tem `DELETE` nem `UPDATE`**:
        # a retencao depende de um prazo fiscal NAO VERIFICADO (dicionario §4,
        # KAM-071), e uma funcao de limpeza contra um prazo por confirmar apaga
        # prova que a lei pode exigir.
        # O `INSERT` do `kamba_app` e do `kamba_batch` e **por coluna** desde o
        # redesenho: sem `criado_at`, sem `prev_hash`, sem `row_hash`. Um
        # privilegio por coluna nao aparece nesta matriz de tabela — aparece em
        # `COLUNAS_POR_PAPEL`, e e la que se le o que falta. Com `INSERT` de
        # tabela inteira, quem escreve forjava uma linha encadeada com a data a
        # escolha (achado C1 da revisao adversarial).
        "audit_log": _auditoria(
            kamba_batch={"SELECT"},
            kamba_audit={"SELECT"},
        ),
        # A cabeca da cadeia nao e o registo: guarda um hash opaco por tenant,
        # e quem escreve precisa de a ler e de a avancar. O `UPDATE` e **por
        # coluna** (`last_hash`), pelo que nao aparece nesta matriz de tabela —
        # aparece em `COLUNAS_POR_PAPEL`. O `kamba_audit` **nao** lhe toca: quem
        # audita recalcula a cadeia a partir do `audit_log`, e uma cabeca que o
        # auditor leia e um valor em que ele poderia passar a confiar.
        # **Nenhum papel de aplicacao lhe escreve.** So o trigger
        # `audit_encadear`, que e `SECURITY DEFINER` e corre como o dono. O
        # `kamba_batch` e o `kamba_audit` leem-na porque verificar a cadeia
        # exige-a: sem a cabeca, apagar as ultimas N linhas deixa-a consistente
        # consigo propria.
        "audit_heads": _auditoria(
            kamba_batch={"SELECT"},
            kamba_audit={"SELECT"},
        ),
        # KAM-009. O `UPDATE` de `tenant_usage` e **por coluna** (`valor`,
        # `actualizado_at`), pelo que nao aparece nesta matriz de tabela —
        # aparece em `COLUNAS_POR_PAPEL`. O `usage_ledger` **nao tem `UPDATE`
        # nenhum**: uma linha dele e o facto de uma chamada ter acontecido, e
        # reescrever um facto nao e corrigir, e apagar.
        #
        # E **nenhum dos dois tem `DELETE` para a aplicacao**, nem sequer
        # para o livro. A primeira versao da funcao desfazia a chave de
        # idempotencia com um `DELETE` quando o tecto recusava; o desfazer
        # passou a ser o rollback de uma subtransaccao, e com isso o
        # privilegio deixou de ser preciso. Quem apaga e o `kamba_batch`, na
        # retencao.
        "tenant_usage": _uso(kamba_app={"SELECT", "INSERT"}),
        "usage_ledger": _uso(kamba_app={"SELECT", "INSERT"}),
    }
)


def _entrada(**por_papel: set[str]) -> dict[str, set[str]]:
    """Matriz de uma tabela da revisao 0008 (KAM-013).

    O dono tem tudo; o `kamba_batch` tem os quatro de dados, porque e quem
    purga a quarentena e quem a tria; `kamba_resolver`, `kamba_identity` e
    `kamba_audit` **nada** — o resolvedor corre depois desta escrita e nao
    antes, a identidade nao sabe de webhooks, e quem audita le o `audit_log`.
    """
    base = {
        "kamba_app": set(),
        "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        "kamba_resolver": set(),
        "kamba_identity": set(),
        "kamba_audit": set(),
        "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
        "public": set(),
    }
    base.update(por_papel)
    return base


ESPERADO_POR_TABELA.update(
    {
        # KAM-013. O `SELECT` do `kamba_app` **e preciso**: o
        # `INSERT ... ON CONFLICT DO NOTHING RETURNING id` e o que distingue
        # uma linha nova de um duplicado, e o PostgreSQL exige `SELECT` na
        # coluna devolvida. A objeccao que levou o `events_dlq` (KAM-006) a nao
        # ter `SELECT` — «um `id` sequencial mede o volume do vizinho» — nao se
        # aplica: aqui o `id` e `gen_random_uuid()` e a tabela nao tem dado de
        # tenant nenhum. O `UPDATE` e **por coluna** (`processado_at`), pelo que
        # nao aparece nesta matriz de tabela.
        "inbound_events": _entrada(kamba_app={"SELECT", "INSERT"}),
        # **Escreve e nao le**, como o `audit_log` — mas aqui por privacidade e
        # nao por nao-repudio: a coluna `payload` guarda o corpo bruto do
        # webhook, que pode levar telefone e texto de mensagem, e quem o
        # escreve nao precisa de o ler. Le quem opera, que e `kamba_batch`.
        # Sem `SELECT`, o `SQL_QUARENTENA` tambem nao pode usar `RETURNING` — e
        # nao usa: a quarentena nao tem de distinguir uma entrada nova de um
        # duplicado, basta nao duplicar.
        #
        # **Nem `UPDATE` nenhum**: quem tria uma quarentena e quem opera.
        "unrouted_events": _entrada(kamba_app={"INSERT"}),
    }
)


def _conversa(**por_papel: set[str]) -> dict[str, set[str]]:
    """Matriz da tabela da revisao 0009 (KAM-014).

    O dono tem tudo; o `kamba_batch` tem os quatro de dados, porque e quem
    purga (KAM-071). O `kamba_resolver` **nada**: ele responde a pergunta
    `phone_number_id -> tenant` antes de haver contexto, e uma conversa so
    existe depois de o contexto existir. O `kamba_audit` tambem nada.
    """
    base = {
        "kamba_app": set(),
        "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        "kamba_resolver": set(),
        "kamba_identity": set(),
        "kamba_audit": set(),
        "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
        "public": set(),
    }
    base.update(por_papel)
    return base


ESPERADO_POR_TABELA.update(
    {
        # KAM-014. A primeira tabela do caminho do webhook com `tenant_id`, e
        # por isso a primeira com RLS: as duas da `0008` nao o tem por desenho,
        # porque o tenant so nasce no CHR.
        #
        # O `kamba_app` le e insere. O `SELECT` **e preciso**: o CHR le o `mode`
        # da conversa, e e o `mode` que decide se a mensagem vai ao AGR
        # (`docs/tecnica/01` §10.2) — e o `INSERT ... ON CONFLICT DO UPDATE ...
        # RETURNING` exige `SELECT` nas colunas devolvidas e nos elementos da
        # inferencia. O `UPDATE` e **por coluna** (`last_inbound_at`,
        # `window_expires_at`), pelo que nao aparece nesta matriz — aparece em
        # `COLUNAS_POR_PAPEL`, e e la que se ve que o `mode` **nao** esta: as
        # transicoes de modo sao KAM-018, e um `UPDATE (mode)` concedido aqui
        # era a aplicacao a poder silenciar uma conversa sem o protocolo desse
        # ticket.
        #
        # O `kamba_identity` aparece a vazio nesta matriz **e tem privilegios**:
        # sao todos por coluna. E o gancho `onContactMerge` do KAM-008 que
        # reaponta as conversas do contacto absorvido, e corre dentro da
        # transacao da fusao, com a ligacao e o contexto que o modulo de
        # identidade abriu — faze-lo por fora quebrava a atomicidade que esse
        # modulo garante. Nem `INSERT` nem `DELETE`: nao cria conversas, e
        # quando o contacto que fica ja tem uma conversa no mesmo canal as duas
        # nao se fundem numa linha (a `UNIQUE` recusa-o) — dobram-se os tempos
        # na que fica e a outra pendura-se na lapide.
        "conversations": _conversa(kamba_app={"SELECT", "INSERT"}),
    }
)


def _saida(**por_papel: set[str]) -> dict[str, set[str]]:
    """Matriz das duas tabelas da revisao 0010 (KAM-015).

    A mesma forma da `_conversa`, e pela mesma razao em cada papel: o dono tem
    tudo, o `kamba_batch` tem os quatro de dados porque e quem purga (KAM-071),
    e o `kamba_resolver`, o `kamba_identity` e o `kamba_audit` **nada** — o
    resolvedor responde antes de haver contexto, a identidade nao sabe de
    envios, e quem audita le o `audit_log`.
    """
    base = {
        "kamba_app": set(),
        "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        "kamba_resolver": set(),
        "kamba_identity": set(),
        "kamba_audit": set(),
        "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
        "public": set(),
    }
    base.update(por_papel)
    return base


ESPERADO_POR_TABELA.update(
    {
        # KAM-015. O `kamba_app` le e insere. O `SELECT` **e preciso**: o
        # adapter le a linha para saber se a chave ja passou (idempotencia) e
        # para recusar um estado que ande para tras (monotonia), e o
        # `INSERT ... ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
        # RETURNING` exige `SELECT` nos elementos da inferencia — a licao que a
        # `0008` escreveu para o `SQL_QUARENTENA`.
        #
        # O `UPDATE` e **por coluna** e por isso nao aparece aqui: esta em
        # `COLUNAS_POR_PAPEL`, e e la que se ve o que **nao** esta — a
        # `idempotency_key`, o `kind` e os quatro identificadores. Reescrever a
        # chave de uma linha que passou e faze-la voltar a passar.
        "outbound_messages": _saida(kamba_app={"SELECT", "INSERT"}),
        # KAM-015. **`SELECT` sem `INSERT`**, e e a diferenca que importa nesta
        # revisao: o adapter **le** os templates para decidir com a janela
        # fechada e **bloqueia** um que seja recategorizado, mas nao cria
        # nenhum. Quem submete o conjunto padrao por tenant e o onboarding
        # (KAM-091), e e esse ticket que pede o `INSERT`. Um `INSERT` concedido
        # aqui era a aplicacao a poder inventar um template aprovado que a Meta
        # nunca viu.
        "message_templates": _saida(kamba_app={"SELECT"}),
    }
)


def _handoff(**por_papel: set[str]) -> dict[str, set[str]]:
    """Matriz das duas tabelas da revisao 0011 (KAM-019).

    A mesma forma da `_saida`, e pela mesma razao em cada papel: o dono tem
    tudo, o `kamba_batch` tem os quatro de dados porque e quem purga (KAM-071),
    e o `kamba_resolver`, o `kamba_identity` e o `kamba_audit` **nada** — o
    resolvedor responde antes de haver contexto, a identidade nao sabe de
    passagens, e quem audita le o `audit_log`.
    """
    base = {
        "kamba_app": set(),
        "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        "kamba_resolver": set(),
        "kamba_identity": set(),
        "kamba_audit": set(),
        "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
        "public": set(),
    }
    base.update(por_papel)
    return base


ESPERADO_POR_TABELA.update(
    {
        # KAM-019. O `kamba_app` le e insere nas duas, e o `UPDATE` e **por
        # coluna** (ver `COLUNAS_POR_PAPEL`).
        #
        # O `SELECT` de tabela e preciso nas duas e nao e generoso: o
        # `openHandoff` le a linha para saber se a passagem ja abriu
        # (idempotencia) e o `INSERT ... ON CONFLICT (handoff_id) DO NOTHING
        # RETURNING` exige `SELECT` na coluna de inferencia — a licao que a
        # `0008` escreveu para o `SQL_QUARENTENA`.
        "handoffs": _handoff(kamba_app={"SELECT", "INSERT"}),
        # **`INSERT` tambem aqui, ao contrario dos `message_templates` da
        # `0010`.** A diferenca e quem cria: um template e submetido pelo
        # onboarding (KAM-091), mas uma conta de atendimento e criada pelo
        # proprio `ensureAccount`, que corre no HND. Negar-lhe o `INSERT` era
        # entregar um criterio que nao pode passar.
        "handoff_accounts": _handoff(kamba_app={"SELECT", "INSERT"}),
        # KAM-020: a mesma forma, e o `kamba_app` tem **tres** verbos e nao
        # dois. O `UPDATE` tem chamador, ao contrario do que a `0011` tentou: a
        # linha nasce em `pendente` com o que a mensagem traz, e so depois da
        # descarga e do `put` e que se sabe o `content_type` real, o `size`, o
        # `sha256` e o `storage_ref`. Sao duas instrucoes **de proposito** — e e
        # isso que faz a idempotencia ser da base e nao do codigo.
        # **`UPDATE` nao entra aqui**, e a razao e a forma do teste: a matriz
        # de tabela le `information_schema.table_privileges`, e um `GRANT
        # UPDATE (coluna)` **nao** aparece la — aparece na matriz de coluna,
        # que esta mais abaixo. Declara-lo aqui fazia o teste exigir um
        # privilegio de tabela que a revisao nao concede, e foi o que a
        # primeira versao fez: treze falhas, sete delas so por isto.
        "media_assets": _handoff(kamba_app={"SELECT", "INSERT"}),
    }
)


def _eventos(**por_papel: set[str]) -> dict[str, set[str]]:
    """Matriz de uma tabela da revisao 0004 (KAM-005).

    O dono tem tudo; `kamba_resolver` e `kamba_identity` **nada** — nao produzem
    nem consomem eventos; `public` nada. O que varia e `kamba_app` (o produtor e
    quem consome) e `kamba_batch` (o publicador, o reconciliador, a operacao da
    DLQ e a retencao), e cada tabela diz o seu.
    """
    base = {
        "kamba_app": set(),
        "kamba_batch": set(),
        "kamba_resolver": set(),
        "kamba_identity": set(),
        "kamba_audit": set(),
        "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
        "public": set(),
    }
    base.update(por_papel)
    return base


ESPERADO_POR_TABELA.update(
    {
        # O produtor insere (sob `WITH CHECK`: o `tenant_id` tem de ser o do
        # contexto) e le as **suas** linhas; nao tem `UPDATE` — o estado de
        # publicacao e do publicador — nem `DELETE`. O `kamba_batch` publica
        # (`SELECT`, `UPDATE`) e purga o publicado (`DELETE`, 7 dias,
        # `docs/tecnica/06` §7.4).
        "events_outbox": _eventos(
            kamba_app={"SELECT", "INSERT"},
            kamba_batch={"SELECT", "UPDATE", "DELETE"},
        ),
        # O contador do `evt_emitir`, que corre como quem chama: o produtor
        # precisa de `INSERT` e `SELECT` de tabela, e de `UPDATE` **so na coluna
        # `seq`** (ver `COLUNAS_POR_PAPEL`). Mudar `agregado_tipo` ou
        # `agregado_id` era reescrever a chave de outro agregado.
        "evt_agregado_seq": _eventos(kamba_app={"SELECT", "INSERT"}),
        # Configuracao de entrega. Quem a le e o publicador; quem a escreve e
        # uma revisao ou um *job* nomeado, com o privilegio pedido no ticket que
        # o criar (KAM-006 em diante).
        "evt_subscricoes": _eventos(kamba_batch={"SELECT"}),
        # Arquivo imutavel: **ninguem** tem `UPDATE` nem `DELETE`. O produtor le
        # o historico das suas linhas (a politica `tenant_iso` filtra-o); o
        # publicador arquiva.
        "events_log": _eventos(
            kamba_app={"SELECT"}, kamba_batch={"SELECT", "INSERT"}
        ),
        # A particao nao herda privilegios do pai — mediu-se: uma particao nova
        # nasce com `relacl` vazio. Fica assim de proposito: quem acede, acede
        # pelo pai, e e la que a politica e os privilegios valem. Uma concessao
        # aqui era um caminho directo que a RLS do pai nao cobre.
        "events_log_default": _eventos(),
        # ------------------------------------------------- KAM-006 (0005)
        # Quem consome escreve a sua linha e le-a (a politica filtra-a); **nao**
        # tem `UPDATE` nem `DELETE`: apagar uma linha de deduplicacao e permitir
        # que o efeito se repita, e isso e da retencao, que corre como
        # `kamba_batch`.
        "events_consumed": _eventos(
            kamba_app={"SELECT", "INSERT"},
            kamba_batch={"SELECT", "DELETE"},
        ),
        # A DLQ e o unico sitio onde `kamba_app` escreve **sem** poder ler a
        # tabela, e e deliberado por duas razoes: o `id` e sequencial, e um
        # papel sujeito a RLS que o lesse media pela sequencia quantas falhas o
        # vizinho teve (dicionario §2); e sem `UPDATE` nem `DELETE`, quem
        # consome nao pode resolver uma entrada sozinho — que e a regra dos dois
        # aprovadores a valer tambem contra codigo, e nao so contra pessoas. Le
        # a tabela e fecha quem opera, que e `kamba_batch`.
        "events_dlq": _eventos(
            # `INSERT` de tabela; o `SELECT` e de **uma coluna** e esta no
            # `COLUNAS_POR_PAPEL`, porque declara-lo aqui dizia que `kamba_app`
            # le o `id` — que e exactamente o que nao pode.
            kamba_app={"INSERT"},
            # Sem `UPDATE` **de tabela**: o que `kamba_batch` tem e `UPDATE` por
            # coluna, e so do desfecho (ver `COLUNAS_POR_PAPEL`). E a mesma
            # forma do `evt_agregado_seq`: um privilegio de coluna nao se
            # declara aqui, ou a matriz de tabela diria que ele altera o
            # envelope e o erro — que sao o registo do que aconteceu.
            kamba_batch={"SELECT", "DELETE"},
        ),
        # As aprovacoes de descarte sao acto de operacao: `kamba_app` nao as ve.
        "evt_dlq_aprovacoes": _eventos(
            kamba_batch={"SELECT", "INSERT", "DELETE"},
        ),
        # As accoes externas: quem consome registra e fecha a sua (o `UPDATE` e
        # por coluna, ver `COLUNAS_POR_PAPEL`); a operacao le.
        "evt_acoes": _eventos(
            kamba_app={"SELECT", "INSERT"},
            kamba_batch={"SELECT"},
        ),
    }
)

#: (papel, tabela, privilegio) -> colunas concedidas **por coluna** nas tabelas
#: da revisao 0003. O que nao esta aqui nao tem privilegio de coluna nenhum.
COLUNAS_POR_PAPEL = {
    ("kamba_app", "contacts", "SELECT"): {
        "contact_id", "tenant_id", "criado_at", "erased_at", "merged_into", "merged_at",
    },
    ("kamba_identity", "contacts", "UPDATE"): {
        "phone_hmac", "hmac_kid", "erased_at", "merged_into", "merged_at",
    },
    ("kamba_identity", "contact_endpoints", "UPDATE"): {
        "contact_id", "bsuid_hmac", "hmac_kid", "phone_enc", "dek_id",
        "recolhido_at", "expira_at",
    },
    ("kamba_identity", "contact_deks", "UPDATE"): {
        "contact_id", "wrapped_dek", "kek_id", "destroyed_at",
    },
    ("kamba_identity", "hmac_key_versions", "UPDATE"): {"estado"},
    # KAM-005: o `evt_emitir` faz `ON CONFLICT ... DO UPDATE SET seq = seq + 1`,
    # e corre como quem chama. E o unico `UPDATE` de `kamba_app` nas tabelas de
    # eventos, e e **uma** coluna.
    ("kamba_app", "evt_agregado_seq", "UPDATE"): {"seq"},
    # KAM-006: o `once(key, fn)` fecha a accao que ele proprio abriu, e so o
    # desfecho. Mudar `consumer`, `event_id` ou `accao` era reescrever a chave
    # de idempotencia de outra accao.
    ("kamba_app", "evt_acoes", "UPDATE"): {"estado", "resultado", "concluido_at"},
    # E a operacao fecha a entrada da DLQ, tambem so o desfecho: o envelope e o
    # erro sao o registo do que aconteceu, e nao se reescrevem.
    ("kamba_batch", "events_dlq", "UPDATE"): {"estado", "resolvido_at", "resolvido_por"},
    # KAM-012: a cabeca da cadeia avanca, e so o hash. Mudar o `tenant_id`
    # de uma cabeca era mudar de cadeia a meio; a `chave` e gerada e nem o
    # dono a escreve.
    # KAM-012: o `INSERT` e por coluna, e as tres que faltam sao a propriedade
    # — `criado_at`, `prev_hash` e `row_hash` sao do trigger, e quem insere nao
    # as escolhe.
    ("kamba_app", "audit_log", "INSERT"): {
        "tenant_id", "actor_type", "actor_id", "action", "entity", "entity_id",
        "turn_id", "payload_hash",
    },
    ("kamba_batch", "audit_log", "INSERT"): {
        "tenant_id", "actor_type", "actor_id", "action", "entity", "entity_id",
        "turn_id", "payload_hash",
    },
    # KAM-006: tres colunas, e nenhuma por gosto. O `ON CONFLICT (consumer,
    # event_id) WHERE estado = 'aberta'` do `paraDlq()` precisa dos dois
    # elementos de inferencia **e** do predicado para o PostgreSQL achar o
    # indice parcial, e as tres entram na verificacao de privilegios como
    # leitura — medido contra o PG 18.6, com `SELECT (estado)` sozinho a nao
    # chegar. O `id` continua fechado, que e a propriedade que importa: a RLS
    # ja limita este papel as linhas do seu tenant, e o que uma sequencia
    # revelaria e o volume do vizinho.
    ("kamba_app", "events_dlq", "SELECT"): {"consumer", "event_id", "estado"},
    # KAM-013: uma coluna, e e a unica que o *worker* escreve depois de
    # inserir. Mudar `kind` ou `event_key` era reescrever a chave de
    # deduplicacao de um evento que ja passou — isto e, fazer com que ele
    # volte a passar. E o `processado_at` existe por causa da janela entre
    # registar e encaminhar: ver `packages/core-ts/src/entrada/registo.ts`.
    ("kamba_app", "inbound_events", "UPDATE"): {"processado_at"},
    # KAM-013: duas colunas, e nao e uma concessao — e o que o
    # `ON CONFLICT (kind, event_key)` do `SQL_QUARENTENA` exige. O PostgreSQL
    # trata os elementos da clausula de inferencia como leitura, e sem eles a
    # insercao falha com 42501 (medido: a quarentena ficava a zero). E a mesma
    # licao do `events_dlq` acima. **O `payload` continua fechado**, que e a
    # propriedade que importa: e a coluna que pode levar telefone e texto.
    ("kamba_app", "unrouted_events", "SELECT"): {"kind", "event_key"},
    # KAM-014: duas colunas, e sao as duas que o CHR escreve em cada entrada —
    # a janela de 24 h abre-se com a mensagem que chega. O `mode` **nao** esta:
    # as transicoes sao KAM-018, e `last_human_activity_at` e de KAM-018/019.
    # Um privilegio concedido «para quando for preciso» e um privilegio que
    # ninguem volta a tirar.
    ("kamba_app", "conversations", "UPDATE"): {"last_inbound_at", "window_expires_at"},
    # KAM-015. Cinco colunas, e sao as que o ciclo de vida muda depois de a
    # linha existir. **O que nao esta aqui e o que importa**: `tenant_id`,
    # `channel_id`, `contact_id`, `conversation_id`, `idempotency_key`, `kind`,
    # `template_name` e `created_at`. Reescrever a `idempotency_key` de uma
    # linha que passou e faze-la voltar a passar — a mesma frase que a `0008`
    # escreveu para o `kind`/`event_key` — e mudar o `kind` depois do envio e
    # reescrever quanto a mensagem custou.
    ("kamba_app", "outbound_messages", "UPDATE"): {
        "state",
        "wamid",
        "pricing",
        "error_code",
        "delivered_at",
    },
    # KAM-015. Seis, e todas vem de **fora**: os tres webhooks de template
    # escrevem `status`, `category` e `quality`; o `meta_template_id` chega na
    # submissao; o `bloqueado_em` e a regra de bloqueio do criterio 9; e o
    # `updated_at` acompanha os outros. **Sem `tenant_id`, `name`, `lang` nem
    # `body_hash`**: os tres primeiros sao a chave primaria — altera-los e fazer
    # o template ser outro — e o `body_hash` e o que permite dizer «o corpo
    # aprovado nao e o corpo que estamos a enviar».
    ("kamba_app", "message_templates", "UPDATE"): {
        "status",
        "category",
        "quality",
        "meta_template_id",
        "bloqueado_em",
        "updated_at",
    },
    # KAM-019. Quatro colunas na passagem, e sao as que o ciclo de vida muda
    # depois de a linha existir. **O que nao esta aqui e o que importa**: o
    # `handoff_id` (reescrever a chave de idempotencia de uma passagem que
    # abriu e faze-la voltar a abrir), o `tenant_id`, o `conversation_id`, o
    # `motivo` — mudar o motivo depois de alguem ter sido chamado e reescrever
    # porque e que foi — e o `opened_at`.
    ("kamba_app", "handoffs", "UPDATE"): {
        "status",
        "external_id",
        "resumed_at",
        "resolver",
    },
    # KAM-019: **nenhuma**, e a entrada fica aqui a dizer isso em vez de
    # desaparecer. A primeira versao da `0011` concedia `UPDATE (inbox_id,
    # bot_id, token_ref, updated_at)`, justificado por o `ensureAccount` «repor»
    # uma conta em falta (`docs/tecnica/01` §11.5) — e a revisao adversarial
    # mediu que esse caminho **nao existe**: o `ensureAccount` faz SELECT,
    # criarConta e INSERT. Era um privilegio de escrita aberto para um caminho
    # inexistente, que e o que a `0009` recusou por escrito. O conjunto vazio
    # afirma a ausencia: se alguem voltar a conceder, este teste falha.
    ("kamba_app", "handoff_accounts", "UPDATE"): set(),
    # KAM-020: **seis** na midia, e a primeira versao tinha sete. A revisao
    # adversarial apanhou a setima: a `classe` **nao** e escrita pelo modulo —
    # ela deriva do `wa_type` na reserva e nao muda —, e conceder `UPDATE` sobre
    # ela permitia reclassificar um objecto, que muda a coluna de que depende a
    # politica de retencao do KAM-071. Era um privilegio sem chamador, o critério
    # pelo qual a `0011` deixou a sua lista vazia. O
    # `asset_id`, o `tenant_id`, o `wamid` e o `media_id` **nao** estao: sao a
    # identidade da linha, e uma identidade que se reescreve nao e identidade —
    # alem de que reescrever o `wamid` ou o `media_id` furava a
    # `media_assets_origem_uq`, que e a idempotencia do criterio 2. O
    # `contact_id` e o `conversation_id` tambem nao: a mensagem veio de uma
    # conversa e nao muda de conversa, e deixa-los alteraveis permitia mover um
    # objecto de midia para outra conversa do **mesmo** tenant, que a FK nao
    # impede e que ninguem precisa.
    ("kamba_app", "media_assets", "UPDATE"): {
        "content_type",
        "size",
        "sha256",
        "storage_ref",
        "estado",
        "retain_until",
    },
    # KAM-014, e e tudo o que o gancho de fusao do KAM-008 precisa: le para
    # encontrar a colisao (o contacto que fica ja tem conversa neste canal?) e
    # para dobrar os tempos, e escreve o `contact_id` e os tres tempos. **Sem
    # `mode`**: uma fusao de contactos nao muda quem tem a palavra numa
    # conversa.
    ("kamba_identity", "conversations", "SELECT"): {
        "id", "tenant_id", "contact_id", "channel_id",
        "last_inbound_at", "window_expires_at", "last_human_activity_at",
    },
    ("kamba_identity", "conversations", "UPDATE"): {
        "contact_id", "last_inbound_at", "window_expires_at", "last_human_activity_at",
    },
}
PRIVILEGIOS_DE_COLUNA = ("SELECT", "INSERT", "UPDATE", "REFERENCES")

#: As tabelas cuja matriz se confere **coluna a coluna**, nos dois sentidos: as
#: quatro da identidade (KAM-008) e as cinco de eventos (KAM-005). Sao as que
#: tem privilegios por coluna, ou onde um privilegio de coluna a mais seria
#: invisivel na matriz de tabela.
TABELAS_COM_MATRIZ_DE_COLUNA = (
    "contacts",
    "contact_deks",
    "contact_endpoints",
    "hmac_key_versions",
    "events_outbox",
    "evt_agregado_seq",
    "evt_subscricoes",
    "events_log",
    "events_log_default",
    # KAM-006: as quatro do consumo. Duas tem privilegio por coluna
    # (`evt_acoes` e `events_dlq`), e as outras duas entram pela mesma razao das
    # de eventos — um privilegio de coluna a mais seria invisivel na matriz de
    # tabela.
    "events_consumed",
    "events_dlq",
    "evt_dlq_aprovacoes",
    "evt_acoes",
    # KAM-012: as duas da auditoria. O `audit_log` **tem** privilegio por
    # coluna — o `INSERT` e sem `criado_at` nem hashes, e e isso que impede
    # quem escreve de forjar uma linha encadeada com a data a escolha. O
    # `audit_heads` entra pela mesma razao das de eventos: um privilegio de
    # coluna a mais nela seria invisivel na matriz de tabela, e escrever na
    # cabeca da cadeia e exactamente o que ninguem pode.
    "audit_log",
    "audit_heads",
    # KAM-013: as duas da entrada. O `inbound_events` **tem** privilegio por
    # coluna (o `UPDATE` e so `processado_at`); o `unrouted_events` entra pela
    # mesma razao das de eventos — um `GRANT SELECT (payload)` ao `kamba_app`
    # seria invisivel na matriz de tabela, e e exactamente o que ninguem pode.
    "inbound_events",
    "unrouted_events",
    # KAM-015: as duas da saida, e entram por uma razao **medida**. A mutacao
    # «a aplicacao passa a poder reescrever a chave de idempotencia» —
    # acrescentar `idempotency_key` as colunas de `UPDATE` de `kamba_app` —
    # **sobreviveu** a primeira volta da prova: a matriz de tabela nao ve um
    # privilegio de coluna a mais, e a verificacao por coluna que havia
    # confirmava que as cinco declaradas estavam concedidas sem exigir que nao
    # houvesse uma sexta. Reescrever a `idempotency_key` de uma linha que passou
    # e faze-la voltar a passar — a idempotencia deste ticket inteiro cai por
    # um `GRANT` de uma palavra.
    "outbound_messages",
    "message_templates",
    # KAM-019: as duas do handoff, pela mesma razao medida no KAM-015 — a
    # matriz de tabela nao ve um privilegio de coluna a mais, e uma mutacao que
    # acrescente uma coluna ao `GRANT UPDATE` sobrevive sem isto.
    "handoffs",
    "handoff_accounts",
    "media_assets",
)

#: Colunas que `kamba_app` **nao** pode alterar depois do insert, e porque.
#:
#: **As tres do KAM-009 sao de outra natureza das que ja ca estavam.** As
#: anteriores sao identidade, chave ou costura: coisas que nao se alteram
#: porque alterar nao faz sentido. Estas tres nao se alteram porque, se se
#: alterassem, **um tenant decidia o proprio tecto** — a politica de `tenants`
#: e por `id = app.tenant_id` (KAM-004), pelo que a linha que um contexto de
#: tenant ve e a dele. Com `UPDATE (plano)` subia o plano; com
#: `UPDATE (limites, ativo)` em `entitlements` subia os limites ou desligava o
#: entitlement. Sao a unica coisa entre um tenant e o tecto de dinheiro por
#: pedido (ADR-013, ADR-015).
#:
#: Estava «por decidir» desde a emenda 1.4 do dicionario e ficou decidido na
#: 1.17.
#:
#: **O `estado` juntou-se-lhes na revisao adversarial, e nao por simetria.** A
#: primeira versao deixou-o alteravel, escrevendo que retira-lo seria decidir
#: o KAM-091 de fora dele. A revisao mediu a consequencia que essa razao nao
#: dizia: `UPDATE platform.tenants SET estado = 'ativo'` com o proprio
#: contexto passa, e o consumo seguinte e aceite. O criterio 2 manda negar um
#: tenant `onboarding`, `suspenso` ou `encerrado` — e o sujeito da condicao
#: nao pode ser quem a retira. O `verificado_at` fica alteravel: nao e entrada
#: de decisao nenhuma, e volta ao §4 com dono.
IMUTAVEIS_PARA_A_APP = {
    "tenants": {
        "id",         # identidade
        "tipo",       # costura do Fluxo B: `platform` -> `pme` tirava-o da vista da guarda
        "criado_at",  # registo
        "plano",      # KAM-009: o plano manda nos entitlements; quem o altera e o batch
        "estado",     # KAM-009: e a condicao do criterio 2; o sujeito nao a retira
    },
    "tenant_channels": {
        "id",         # identidade
        "tenant_id",  # mover um canal de tenant entregava mensagens de um negocio a outro
        "origem",     # costura do Fluxo B
    },
    "entitlements": {
        "tenant_id",  # chave
        "modulo",     # chave
        "limites",    # KAM-009: subir o proprio tecto
        "ativo",      # KAM-009: desligar o proprio entitlement e o fail-closed com ele
    },
    # KAM-009. O contador so se altera pelo caminho que o faz cumprir o tecto:
    # `valor` e `actualizado_at`, e a funcao `platform.ten_consumir`. O resto
    # e chave.
    "tenant_usage": {
        "tenant_id",
        "chave_limite",
        "periodo",
    },
    # O livro **nao se altera de todo**: uma linha dele e o facto de uma
    # chamada ter acontecido. Reescrever a `quantidade` depois do facto era
    # reescrever o consumo; mudar a `chave_limite` era move-lo de contador.
    # A aplicacao insere e apaga (o desfazer da propria transaccao, quando o
    # tecto recusa), e nao actualiza.
    "usage_ledger": {
        "tenant_id",
        "idempotency_key",
        "chave_limite",
        "periodo",
        "quantidade",
        "criado_at",
    },
    # KAM-013. So `processado_at` se altera, e e o que fecha a janela entre
    # registar e encaminhar. Tudo o mais e a identidade do evento: mudar
    # `kind` ou `event_key` era fazer um evento ja tratado voltar a passar.
    "inbound_events": {
        "id",
        "kind",
        "event_key",
        "waba_id",
        "phone_number_id",
        "recebido_at",
    },
    # A quarentena **nao se altera de todo** pela aplicacao: uma linha dela e
    # o facto de um corpo nao ter encaixado, e quem a tria e quem opera.
    "unrouted_events": {
        "id",
        "kind",
        "event_key",
        "waba_id",
        "phone_number_id",
        "motivo",
        "payload",
        "recebido_at",
        "processado_at",
    },
}


class TestPertencas(ComBase):
    def test_nenhum_dos_tres_papeis_pertence_a_outro_nem_tem_membros(self) -> None:
        linhas = self.consultar(
            "SELECT g.rolname, m.rolname FROM pg_auth_members a "
            "JOIN pg_roles g ON g.oid = a.roleid JOIN pg_roles m ON m.oid = a.member "
            "WHERE g.rolname = ANY(%s) OR m.rolname = ANY(%s)",
            (list(ligacao.PAPEIS.values()), list(ligacao.PAPEIS.values())),
        )
        self.assertEqual(linhas, [])

    def test_o_bootstrap_revoga_uma_pertenca_posta_a_mao(self) -> None:
        """`GRANT kamba_batch TO kamba_app` e o atalho para contornar a RLS."""
        admin = ligacao.ligar("admin")
        admin.autocommit = True
        try:
            cursor = admin.cursor()
            cursor.execute("GRANT kamba_batch TO kamba_app")
            cursor.execute("GRANT kamba_migrator TO kamba_app")
            feito = bootstrap.aplicar()
            self.assertEqual(sum("pertenca revogada" in linha for linha in feito), 2)
            cursor.execute(
                "SELECT count(*) FROM pg_auth_members a "
                "JOIN pg_roles m ON m.oid = a.member WHERE m.rolname = 'kamba_app'"
            )
            self.assertEqual(cursor.fetchone()[0], 0)
        finally:
            admin.close()

    def test_kamba_app_nao_assume_outro_papel(self) -> None:
        cursor = self.ligar("app").cursor()
        for papel in ("kamba_migrator", "kamba_batch"):
            with self.subTest(papel=papel):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, f"SET ROLE {papel}")

    def test_o_bootstrap_apaga_configuracao_posta_a_mao(self) -> None:
        admin = ligacao.ligar("admin")
        admin.autocommit = True
        try:
            cursor = admin.cursor()
            cursor.execute("ALTER ROLE kamba_app SET search_path = intrusa, public")
            bootstrap.aplicar()
            cursor.execute(
                "SELECT rolconfig FROM pg_roles WHERE rolname = 'kamba_app'"
            )
            self.assertIsNone(cursor.fetchone()[0])
        finally:
            admin.close()


class TestMatrizDePrivilegios(ComBase):
    """A matriz exacta: nem um privilegio a menos, nem um a mais."""

    def test_privilegios_de_tabela(self) -> None:
        # Uma so ligacao para a matriz inteira: uma por celula esgotava as do servidor.
        cursor = self.ligar("admin").cursor()
        for tabela in TABELAS:
            for papel, esperados in ESPERADO_POR_TABELA[tabela].items():
                for privilegio in PRIVILEGIOS_DE_TABELA:
                    with self.subTest(papel=papel, tabela=tabela, privilegio=privilegio):
                        cursor.execute(
                            "SELECT has_table_privilege(%s, %s, %s)",
                            (papel, f"platform.{tabela}", privilegio),
                        )
                        self.assertEqual(cursor.fetchone()[0], privilegio in esperados)

    def test_a_matriz_cobre_todos_os_papeis_do_bootstrap(self) -> None:
        """Um papel novo que ninguem ponha na matriz e um papel por medir."""
        self.assertEqual(set(ESPERADO_POR_TABELA), set(TABELAS))
        for tabela, por_papel in ESPERADO_POR_TABELA.items():
            with self.subTest(tabela=tabela):
                self.assertEqual(
                    set(por_papel) - {"public"}, set(ligacao.PAPEIS.values())
                )

    def test_privilegios_por_coluna_nas_tabelas_com_matriz(self) -> None:
        """Coluna a coluna, nos dois sentidos, para todos os papeis menos o dono.

        `has_column_privilege` tambem responde `true` quando o privilegio e de
        tabela; por isso o esperado e a uniao dos dois. Um `GRANT UPDATE
        (tenant_id)` a `kamba_identity`, um `GRANT SELECT (phone_hmac)` a
        `kamba_app`, ou um `GRANT UPDATE (publicado_at)` a `kamba_app` no outbox
        (KAM-005), aparece aqui como uma coluna a mais.
        """
        # Uma consulta **por tabela**, e nao uma por celula: com as cinco
        # tabelas de eventos (KAM-005) a matriz passou a ter perto de 2 500
        # celulas, e uma ida a base por celula levava a suite ao limite de
        # tempo do gate. O `unnest` cruzado devolve a matriz inteira de uma vez;
        # as asercoes sao as mesmas, celula a celula.
        # Os papeis vem do `ligacao.PAPEIS` e nao de uma tupla escrita a mao:
        # o `kamba_audit` (KAM-012) nasceu e esta lista nao o acompanhou, e um
        # papel que falte aqui e um papel a quem se pode conceder uma coluna
        # sem ninguem ver. E a mesma licao do `EXECUTE` para `PUBLIC`.
        papeis = (*sorted(ligacao.PAPEIS.values()), "public")
        cursor = self.ligar("admin").cursor()
        for tabela in TABELAS_COM_MATRIZ_DE_COLUNA:
            cursor.execute(
                "SELECT r.papel, c.column_name::text, p.priv, "
                "       has_column_privilege(r.papel, %s, c.column_name, p.priv) "
                "  FROM unnest(%s::text[]) AS r(papel) "
                " CROSS JOIN unnest(%s::text[]) AS p(priv) "
                " CROSS JOIN information_schema.columns c "
                " WHERE c.table_schema = 'platform' AND c.table_name = %s",
                (f"platform.{tabela}", list(papeis), list(PRIVILEGIOS_DE_COLUNA), tabela),
            )
            matriz = {(p, c, v): bool(tem) for p, c, v, tem in cursor.fetchall()}
            colunas = sorted({c for _, c, _ in matriz})
            self.assertTrue(colunas, f"{tabela} sem colunas")
            for papel in papeis:
                for privilegio in PRIVILEGIOS_DE_COLUNA:
                    de_tabela = privilegio in ESPERADO_POR_TABELA[tabela][papel]
                    por_coluna = COLUNAS_POR_PAPEL.get((papel, tabela, privilegio), set())
                    self.assertTrue(por_coluna <= set(colunas), "coluna inexistente na matriz")
                    for coluna in colunas:
                        with self.subTest(
                            papel=papel, coluna=f"{tabela}.{coluna}", privilegio=privilegio
                        ):
                            self.assertEqual(
                                matriz[(papel, coluna, privilegio)],
                                de_tabela or coluna in por_coluna,
                            )

    def test_ninguem_pode_passar_privilegios_adiante(self) -> None:
        """Nenhum papel pode re-conceder o que tem: `WITH GRANT OPTION` a zero.

        **Uma consulta, e nao uma por celula**, e isto foi medido. A primeira
        versao abria uma ligacao por `(papel, tabela)` — o `consultar` abre uma
        e so a fecha no `tearDown` — e com as duas tabelas da `0011` as quatro
        vezes vinte e sete passaram do `max_connections` da base descartavel:
        oito celulas morriam com `53300 sorry, too many clients already`, que
        nao e um privilegio a mais nem a menos, e a suite ficava vermelha sobre
        **nada**. Era um defeito latente a espera de uma tabela nova, e e a
        mesma licao que o `test_privilegios_por_coluna_nas_tabelas_com_matriz`
        ja tinha escrito para a matriz de colunas.

        A asserçao e sobre a **lista** dos que teem a opcao, e nao celula a
        celula com `subTest`: a mensagem de falha passa a nomear todos os
        infractores de uma vez, em vez de um por linha de relatorio.
        """
        papeis = ("kamba_app", "kamba_batch", "kamba_resolver", "kamba_identity")
        linhas = self.consultar(
            "SELECT r.papel, t.tabela, "
            "       has_table_privilege(r.papel, 'platform.' || t.tabela, "
            "                           'SELECT WITH GRANT OPTION') "
            "  FROM unnest(%s::text[]) AS r(papel) "
            " CROSS JOIN unnest(%s::text[]) AS t(tabela)",
            (list(papeis), list(TABELAS)),
        )
        self.assertEqual(len(linhas), len(papeis) * len(TABELAS))
        self.assertEqual([(p, t) for p, t, tem in linhas if tem], [])

    def test_update_por_coluna_da_app(self) -> None:
        """Todas as colunas menos as imutaveis — e a lista confere-se nos dois sentidos."""
        for tabela, imutaveis in IMUTAVEIS_PARA_A_APP.items():
            colunas = self.consultar(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'platform' AND table_name = %s",
                (tabela,),
            )
            nomes = {c for (c,) in colunas}
            self.assertTrue(imutaveis <= nomes, f"coluna imutavel inexistente em {tabela}")
            for coluna in sorted(nomes):
                with self.subTest(coluna=f"{tabela}.{coluna}"):
                    pode = self.consultar(
                        "SELECT has_column_privilege('kamba_app', %s, %s, 'UPDATE')",
                        (f"platform.{tabela}", coluna),
                    )[0][0]
                    self.assertEqual(pode, coluna not in imutaveis)

    def test_nao_ha_privilegios_por_omissao(self) -> None:
        """Sem `ALTER DEFAULT PRIVILEGES`: uma tabela nova nao nasce acessivel."""
        self.assertEqual(self.consultar("SELECT count(*) FROM pg_default_acl"), [(0,)])

    def test_public_nao_tem_nada_na_base(self) -> None:
        base = ligacao.alvo().base
        linhas = self.consultar(
            "SELECT has_database_privilege('public', %s, 'TEMPORARY'), "
            "has_database_privilege('public', %s, 'CONNECT'), "
            "has_database_privilege('kamba_app', %s, 'CONNECT'), "
            "has_database_privilege('kamba_app', %s, 'TEMPORARY'), "
            "has_database_privilege('kamba_app', %s, 'CREATE')",
            (base, base, base, base, base),
        )
        self.assertEqual(linhas, [(False, False, True, False, False)])


class TestOQueAAppNaoConsegue(ComBase):
    """O efeito, tentado: cada uma destas instrucoes era aceite na primeira versao."""

    def setUp(self) -> None:
        super().setUp()
        # **As sementes deixaram de ir pela ligacao da aplicacao.** Desde a
        # revisao adversarial do KAM-009 ela nao tem `INSERT` em
        # `entitlements`, e semear com ela era semear com o privilegio que
        # esta classe existe para provar que nao existe. Vao por uma ligacao
        # de administrador em `autocommit`, e apagam-se no fim.
        self._semente = ligacao.ligar("admin")
        self._semente.autocommit = True
        semente = self._semente.cursor()
        self.tenant = factories.tenant(semente)
        self.canal = factories.canal(semente, self.tenant)
        factories.entitlement(semente, self.tenant, limites={"msgs_ai_mes": 10})
        self.addCleanup(self._apagar_a_semente)

        self.conexao = self.ligar("app")
        self.cursor = self.conexao.cursor()
        # O contexto vinha da fabrica, que agora corre noutra ligacao.
        factories.contexto(self.cursor, self.tenant)

    def _apagar_a_semente(self) -> None:
        cursor = self._semente.cursor()
        try:
            for tabela in (
                "usage_ledger", "tenant_usage", "entitlements", "tenant_channels"
            ):
                cursor.execute(
                    f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (self.tenant,)
                )
            cursor.execute(
                "DELETE FROM platform.tenants WHERE id = %s", (self.tenant,)
            )
        finally:
            self._semente.close()

    def test_nao_apaga_linhas_de_tabela_nenhuma(self) -> None:
        """Dicionario §2: «soft delete: estado, nunca DELETE». Nas sete tabelas."""
        for tabela in TABELAS:
            with self.subTest(tabela=tabela):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, self.cursor, f"DELETE FROM platform.{tabela}"
                )

    def test_nao_muda_o_tipo_de_um_tenant(self) -> None:
        """Um tenant `platform` que passasse a `pme` saia da vista da guarda."""
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            self.cursor,
            "UPDATE platform.tenants SET tipo = 'courier' WHERE id = %s",
            (self.tenant,),
        )

    def test_nao_move_um_canal_para_outro_tenant(self) -> None:
        outro = factories.tenant(self.cursor)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            self.cursor,
            "UPDATE platform.tenant_channels SET tenant_id = %s WHERE id = %s",
            (outro, self.canal),
        )

    def test_nao_muda_a_origem_de_um_canal(self) -> None:
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            self.cursor,
            "UPDATE platform.tenant_channels SET origem = 'plataforma' WHERE id = %s",
            (self.canal,),
        )

    def test_nao_cria_tabelas_temporarias(self) -> None:
        """O criterio diz «`CREATE TABLE` sob `kamba_app` falha», sem excepcao."""
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, self.cursor, "CREATE TEMP TABLE t_app (x integer)"
        )

    def test_continua_a_poder_o_que_deve(self) -> None:
        """A correccao nao pode ter tirado a aplicacao o que ela precisa."""
        # O `estado` **saiu** desta lista com a revisao adversarial: a
        # aplicacao continua a alterar o nome e o resto do perfil, e quem
        # mexe no estado do tenant e o `kamba_batch` (ver
        # `test_nao_consegue_retirar_a_condicao_do_criterio_2`).
        self.cursor.execute(
            "UPDATE platform.tenants SET nome = 'Outro nome' WHERE id = %s",
            (self.tenant,),
        )
        self.cursor.execute(
            "UPDATE platform.tenant_channels SET estado = 'ativo', "
            "quality_rating = 'GREEN' WHERE id = %s",
            (self.canal,),
        )
        # O `UPDATE` de `entitlements` **saiu daqui com o KAM-009**, e a
        # substituicao nao e cosmetica: o que a aplicacao precisa de poder
        # fazer com entitlements e **consumir contra eles**, nao reescreve-los.
        # Quem os reescreve e o `kamba_batch` — ver `TestOBatch` abaixo.
        self.cursor.execute(
            "SELECT aceite, valor FROM platform.ten_consumir("
            "  %s, 'msgs_ai_mes', 1, %s)",
            (self.tenant, f"canario-{self.tenant}"),
        )
        aceite, valor = self.cursor.fetchone()
        self.assertTrue(aceite, "a aplicacao tem de conseguir consumir um limite")
        self.assertEqual(valor, 1)
        self.cursor.execute(
            "SELECT count(*) FROM platform.tenant_channels WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 1)

    def test_nao_consegue_subir_o_proprio_tecto(self) -> None:
        """A decisao do KAM-009, pelo lado que interessa.

        Nao basta que o `has_column_privilege` diga nao: o que isto mede e o
        que acontece quando a aplicacao **tenta**, com o seu proprio contexto
        de tenant, que e o caso real — a politica de `tenants` e por
        `id = app.tenant_id`, pelo que a linha que ela ve e a dela.

        **O `INSERT` estava em falta, e era um critico.** Esta lista tinha
        tres `UPDATE`s e nenhum `INSERT`, e a revisao adversarial mediu a
        porta que isso deixava aberta: com `WITH CHECK (tenant_id =
        app.tenant_id)`, um tenant **insere a propria linha** de
        `entitlements` com o tecto que quiser, e um pedido de 500 000 000 que
        era negado passa a ser aceite. Nao e preciso subir o proprio tecto se
        se pode criar um. Um teste que so sabe nomear um verbo prova um
        verbo.
        """
        for instrucao, argumentos in (
            ("UPDATE platform.tenants SET plano = 'ilimitado' WHERE id = %s",
             (self.tenant,)),
            ("UPDATE platform.entitlements SET limites = '{\"msgs_ai_mes\": 999999}'::jsonb "
             "WHERE tenant_id = %s", (self.tenant,)),
            ("UPDATE platform.entitlements SET ativo = false WHERE tenant_id = %s",
             (self.tenant,)),
            # O critico: criar um entitlement em vez de alterar o que ha.
            ("INSERT INTO platform.entitlements (tenant_id, modulo, limites, ativo) "
             "VALUES (%s, 'auto', '{\"valor_max_pedido_minor\": 900000000000}'::jsonb, true)",
             (self.tenant,)),
            # E a variante que nem precisa de nomear um modulo novo: declarar
            # uma chave que nenhum modulo activo declarava, onde o minimo de
            # um conjunto de um elemento e esse elemento.
            ("INSERT INTO platform.entitlements (tenant_id, modulo, limites) "
             "VALUES (%s, 'catalogo', '{\"msgs_ai_mes\": 999999}'::jsonb)",
             (self.tenant,)),
        ):
            with self.subTest(instrucao=instrucao.split(" SET ")[0][:48]):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, self.cursor, instrucao, argumentos
                )

    def test_nao_consegue_retirar_a_condicao_do_criterio_2(self) -> None:
        """Um tenant `suspenso` nao se reactiva a si proprio.

        O criterio 2 manda negar `onboarding`, `suspenso` e `encerrado`. A
        revisao adversarial mediu que a aplicacao fazia
        `UPDATE platform.tenants SET estado = 'ativo'` com o proprio
        contexto e o consumo seguinte era aceite: o sujeito da condicao
        retirava a condicao. O `UPDATE (estado)` saiu da lista da `0007`.
        """
        for estado in ("ativo", "onboarding", "encerrado"):
            with self.subTest(estado=estado):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE,
                    self.cursor,
                    "UPDATE platform.tenants SET estado = %s WHERE id = %s",
                    (estado, self.tenant),
                )

    def test_nao_consegue_zerar_o_proprio_contador(self) -> None:
        """O terceiro critico: `UPDATE (valor)` nao diz em que direccao.

        A aplicacao precisa de `UPDATE (valor, actualizado_at)` para o
        `ON CONFLICT DO UPDATE` da `ten_consumir`; o privilegio nao sabe
        exprimir «so sobe», e o trigger `tenant_usage_so_sobe` sabe. Sem ele,
        medido: consumir dez contra um tecto de dez, pôr o contador a zero, e
        consumir outros dez.
        """
        self.cursor.execute(
            "SELECT aceite FROM platform.ten_consumir(%s, 'msgs_ai_mes', 10, %s)",
            (self.tenant, f"zerar-{self.tenant}"),
        )
        self.assertTrue(self.cursor.fetchone()[0])
        for instrucao in (
            "UPDATE platform.tenant_usage SET valor = 0",
            "UPDATE platform.tenant_usage SET valor = valor - 1",
        ):
            with self.subTest(instrucao=instrucao):
                self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, instrucao)
        # E o caminho legitimo continua aberto: subir.
        self.cursor.execute("UPDATE platform.tenant_usage SET valor = valor")
        self.cursor.execute(
            "SELECT valor FROM platform.tenant_usage WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 10)


class TestOBatch(ComBase):
    def test_apaga_e_altera_tudo(self) -> None:
        """Retencao e correccoes sao do `kamba_batch`, auditado (doc 08 §3.3)."""
        cursor = self.ligar("batch").cursor()
        tenant = factories.tenant(cursor, tipo="platform")
        factories.entitlement(cursor, tenant)
        cursor.execute("UPDATE platform.tenants SET tipo = 'pme' WHERE id = %s", (tenant,))
        cursor.execute("DELETE FROM platform.entitlements WHERE tenant_id = %s", (tenant,))
        cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (tenant,))
