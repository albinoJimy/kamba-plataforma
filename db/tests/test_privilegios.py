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
    TABELAS_DAT_COM_MATRIZ,
    TABELAS_SERVICOS_COM_MATRIZ,
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


def _idempotencia(**por_papel: set[str]) -> dict[str, set[str]]:
    """Matriz da `tool_idempotency` (revisao 0022, KAM-029).

    Helper proprio e nao o `_uso` nem o `_auditoria`, porque nenhum dos dois
    diz a verdade sobre esta tabela: o `_uso` da ao `kamba_batch` os quatro
    privilegios de dados e aqui ele so purga, e o `_auditoria` poe o
    `kamba_app` a zero e aqui ele le — sem leitura nao ha *replay*.
    """
    base = {
        "kamba_app": {"SELECT"},
        "kamba_batch": {"SELECT", "DELETE"},
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
        # KAM-021: o registo das transicoes. `SELECT` e `INSERT` e mais nada,
        # como a `media_assets` — e aqui o `UPDATE` **nao existe de todo**,
        # nem de tabela nem de coluna: uma linha deste registo e o facto de a
        # Meta ter dito uma coisa a uma hora, e um facto nao se corrige.
        "channel_quality_log": _handoff(kamba_app={"SELECT", "INSERT"}),
        "media_assets": _handoff(kamba_app={"SELECT", "INSERT"}),
        # KAM-022: a prova de consentimento. `SELECT` e `INSERT` e mais nada,
        # como o `channel_quality_log` — e aqui o *append-only* e **criterio**
        # e nao consequencia: «`UPDATE/DELETE` recusados para `kamba_app`». Uma
        # prova de consentimento que se possa corrigir nao e prova.
        "consent_event": _handoff(kamba_app={"SELECT", "INSERT"}),
        # O texto do aviso: a aplicacao **le** e nao escreve. Quem publica uma
        # versao nova e operacao, com o papel de administracao — e e por isso
        # que o `kamba_batch` tem os quatro. Dar `INSERT` a aplicacao deixava o
        # caminho que serve clientes publicar um texto juridico.
        "consent_texts": _handoff(kamba_app={"SELECT"}),
        # KAM-016: a tentativa de onboarding. **`SELECT` e mais nada**, e e a
        # primeira tabela deste esquema em que `kamba_app` **le e nao escreve**:
        # a `message_templates` le e altera, a `events_dlq` escreve e nao le,
        # esta so le. A razao e que o onboarding de um canal e
        # **provisionamento**, e o dicionario §3.2 ja lho atribuiu — «quem os
        # altera e o kamba_batch — provisionamento (KAM-091) e cobranca
        # (KAM-059) sao de retaguarda e ja la correm». O `SELECT` existe porque
        # o painel da loja le em que fase esta o seu canal (KAM-093).
        "channel_onboarding": _handoff(kamba_app={"SELECT"}),
        # KAM-017: o estado de coexistencia. **`kamba_app` escreve**, e e a
        # diferenca face a linha acima: o onboarding e provisionamento e corre
        # de retaguarda, mas a coexistencia corre no **caminho de um webhook** —
        # um `echo` chega, um `history` chega —, e quem trata webhooks e o
        # `worker-canal` com o papel `kamba_app` sob RLS `FORCE`. Dar isto ao
        # `kamba_batch` obrigava o tratador de um webhook a mudar de papel a
        # meio. **Sem `DELETE`**, pela regra da `0001`: «soft delete: estado,
        # nunca DELETE».
        "channel_coexistence": _handoff(
            # **Sem `UPDATE` de tabela**, e e isso que torna a matriz de coluna
            # abaixo significativa: o `test_privilegios_por_coluna_nas_tabelas_
            # com_matriz` compara `de_tabela or coluna in por_coluna`, e um
            # `UPDATE` de tabela curto-circuita o `or` — a lista nunca era
            # confrontada. Achado da revisao adversarial, e e o mesmo que a
            # `channel_onboarding` evita por `kamba_app` nao ter `UPDATE` de
            # todo.
            kamba_app={"SELECT", "INSERT"},
            # **Com `UPDATE`**, e e indispensavel: as tres varreduras do
            # criterio 3 e do 6 sao `UPDATE` **sem `tenant_id` no predicado**,
            # pelo que so correm com `BYPASSRLS` — e o `kamba_batch` e o unico
            # papel que o tem (`db/bootstrap.py`). Sem isto respondiam `42501`.
            kamba_batch={"SELECT", "UPDATE", "DELETE"},
        ),
        # KAM-115. As duas do aviso ao dono, e as duas **sem `UPDATE` de
        # tabela** para o `kamba_app`, pela razao que a `0018` pagou: o
        # `test_privilegios_por_coluna_nas_tabelas_com_matriz` compara
        # `de_tabela or coluna in por_coluna`, e um `UPDATE` de tabela
        # curto-circuita o `or` — a lista de colunas nunca era confrontada.
        "owner_contacts": _handoff(
            kamba_app={"SELECT", "INSERT"},
            # **Sem `INSERT` para o `kamba_batch`**, e e a unica assimetria entre
            # as duas tabelas deste ticket: quem capta o endereco e o caminho do
            # dono (KAM-086) e nao um *job* de retaguarda. O que o `kamba_batch`
            # faz aqui e a varredura do criterio 6 — os tenants `ativo` sem
            # contacto verificado —, que e `SELECT`, e marcar invalido o que
            # deu *bounce*, que e `UPDATE` **sem `tenant_id` no predicado** e so
            # corre com `BYPASSRLS`.
            kamba_batch={"SELECT", "UPDATE", "DELETE"},
        ),
        "owner_notices": _handoff(
            kamba_app={"SELECT", "INSERT"},
            # **Com `INSERT`**, ao contrario da tabela acima: os lembretes das
            # 24 h e das 72 h do criterio 4 sao escritas de retaguarda, e sem
            # `INSERT` o «lembretes se o estado persiste» nao tinha caminho
            # executavel — so decisao escrita. E a mesma classe de achado que a
            # revisao adversarial da `0018` mediu nas varreduras dela.
            kamba_batch={"SELECT", "INSERT", "UPDATE", "DELETE"},
        ),
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

ESPERADO_POR_TABELA.update(
    {
        # ------------------------------------------------- KAM-028 (0021)
        #
        # **Quem escreve nao le**, como na `audit_log` e pela mesma razao: quem
        # produz o registo nao e quem o audita, e um `SELECT` concedido ao
        # processo que corre os turnos era um caminho para o conteudo do registo
        # voltar a um turno. Quem le e o `kamba_audit` e o `kamba_batch`.
        #
        # O `kamba_app` aparece aqui **vazio** porque o `INSERT` dele e por
        # coluna — sem `id` e sem `ts` — e um privilegio de coluna nao se
        # declara nesta matriz: esta em `COLUNAS_POR_PAPEL`. Declara-lo aqui
        # dizia que ele escolhe o instante da sua propria linha de auditoria.
        #
        # **Ninguem tem `UPDATE` nem `DELETE`**, e o `kamba_migrator` tem tudo
        # porque e o dono: o privilegio de tabela nao mostra o *append-only*, e
        # quem o impoe e o *trigger* `ENABLE ALWAYS`, que esta bateria nao ve.
        # Prova-se em `db/tests_agr/test_tool_audit.py`.
        "tool_audit": _auditoria(
            kamba_batch={"SELECT"},
            kamba_audit={"SELECT"},
        ),
        # KAM-030: o registo de chamadas a modelos (revisao `0023`), no esquema
        # `dat`. A matriz e a mesma da `tool_audit`, e por uma razao que nao e
        # simetria: as duas sao *append-only* e nas duas **quem escreve nao le**
        # — um `SELECT` concedido ao processo que escreve e um caminho para o
        # custo de outro *tenant* voltar a um turno.
        #
        # O `kamba_batch` le e **nao apaga**: a retencao desta tabela e um `DROP`
        # de particao (`docs/tecnica/06` §9.3), que exige ser dono.
        #
        # O `kamba_app` aparece sem nada de tabela e com `INSERT` **por coluna**
        # em `COLUNAS_POR_PAPEL`, que e onde a afirmacao que importa vive.
        # Prova-se em `db/tests_agr/test_llm_call_log.py`.
        "llm_call_log": _auditoria(
            kamba_batch={"SELECT"},
            kamba_audit={"SELECT"},
        ),
        # KAM-029: a barreira de idempotencia (revisao `0022`).
        #
        # **Nao e uma tabela de auditoria e nao usa o `_auditoria`**: ali
        # ninguem altera nada e e o *trigger* que o impoe; aqui o protocolo do
        # §6.3 **tem** de alterar — `em_curso` -> `concluida` — e o que o
        # protege e o `UPDATE` por coluna, que esta matriz nao ve. Por isso ela
        # esta tambem em `TABELAS_COM_MATRIZ_DE_COLUNA`, e e la que a afirmacao
        # que importa vive.
        #
        # O `kamba_app` aparece com `SELECT` e mais nada, e o `SELECT` **esta**
        # aqui ao contrario da `tool_audit`: ali um `SELECT` era um caminho para
        # o conteudo de um registo voltar a um turno, aqui a leitura e a funcao
        # — sem ela nao ha *replay*. O `INSERT` e o `UPDATE` dele sao por coluna.
        #
        # O `kamba_batch` tem `SELECT, DELETE` e nao os quatro de dados que tem
        # nas tabelas do `_uso`: quem purga nao insere nem altera. O
        # `kamba_audit` nao tem nada, pela razao que o `_uso` escreveu para os
        # contadores — quem audita le o `audit_log`.
        "tool_idempotency": _idempotencia(),
        # KAM-114 (0024). **O `kamba_app` tem so `SELECT` ao nivel da tabela**, e
        # isso nao e um privilegio a menos: o `INSERT` e o `UPDATE` dele sao
        # **por coluna** (seis em cada), e o `has_table_privilege` que esta
        # matriz usa nao conta privilegio de coluna — a mesma forma da
        # `tool_idempotency` e da `dat.llm_call_log`. A leitura ele tem porque o
        # *compare-and-set* precisa de classificar o seu proprio rascunho (o
        # duplo clique contra a recusa) e a varredura precisa de o encontrar.
        #
        # **Sem `DELETE` para o `kamba_app`**, e com `DELETE` para o
        # `kamba_batch`: a retencao e do lote (KAM-071) e uma decisao gravada nao
        # se apaga a pedido de quem a produziu — a razao que a `0005` escreveu
        # para o consumidor da DLQ. O lote tem tambem `UPDATE`, porque e ele que
        # atravessa *tenants* na varredura dos prazos.
        #
        # O `kamba_audit` le, e e ele que le a vista `v_draft_metrics`: quem
        # produz as decisoes nao e quem as audita (KAM-030).
        "draft_decisions": {
            "kamba_app": {"SELECT"},
            "kamba_batch": {"SELECT", "UPDATE", "DELETE"},
            "kamba_audit": {"SELECT"},
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
        # KAM-052: a conta de pagamento (revisao `0027`).
        #
        # **O `kamba_app` **le** e nao escreve**, e isso distingue esta tabela da
        # `bookings` do `servicos`. Quem cria e altera uma conta de pagamento e o
        # onboarding de retaguarda (KAM-091) e o fluxo de activacao do
        # `docs/tecnica/04` secao 10.2, nao um turno de conversa. Com `INSERT`
        # concedido e `WITH CHECK (tenant_id = app.tenant_id)`, um tenant criava
        # as proprias contas — isto e, declarava para onde vai o dinheiro das
        # suas vendas sem ninguem verificar os documentos que a secao 10.2
        # recolhe. E a mesma escolha que a `0007` fez ao tirar `INSERT` em
        # `entitlements` a este papel, e que a `0025` fez para o catalogo da
        # agenda.
        #
        # **E ninguem apaga.** Encerrar uma conta e `estado = 'revogado'` (secao
        # 10.2); um `DELETE` concedido tornava o historico de beneficiarios
        # reescrivel, que e exactamente o que a G-1 existe para poder auditar.
        #
        # **O `kamba_batch` apaga**, e a primeira versao desta matriz nao lhe dava
        # `DELETE`: o *gate* 6 recusou com `42501` em dez `tearDownClass`, porque
        # o semeador da bateria de isolamento nao conseguia limpar o que semeou.
        # Nao e uma folga — e a regra que a `0025` ja escreve por extenso («quem
        # apaga e o `kamba_batch`, que e o papel da retencao (KAM-071) e o
        # semeador das baterias de isolamento») e que o dicionario §2 ressalva
        # («soft delete: estado, nunca `DELETE`, **salvo purga prevista**»).
        #
        # **O `kamba_audit` le**, porque «para onde foi o dinheiro desta venda» e
        # uma pergunta de auditoria. O `GRANT` nao o poe acima da RLS: ele nao
        # tem `BYPASSRLS` (so o `kamba_batch` tem), pelo que ve as contas do
        # tenant cujo contexto tiver e **nao** ve a de `tenant_id` nulo.
        "payment_accounts": {
            "kamba_app": {"SELECT"},
            "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            "kamba_audit": {"SELECT"},
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
        # ------------------------------------------------- KAM-043 (0028)
        #
        # **O `kamba_app` escreve, e isso distingue estas duas da
        # `payment_accounts` acima e das tabelas do `dat`.** Ali o papel da
        # aplicacao le (ou insere e nao le), porque quem produz um registo de
        # custo ou quem consome uma conta nao e quem a cria. Aqui os termos de
        # uma oferta **sao** o estado de negocio que a porta
        # `CommerceRegistry` le e escreve — o `upsertProductDraft`, o
        # `publishProduct` e o ajuste de preco e de stock sao todos dele —, e
        # e a RLS `FORCE` que o limita as linhas do tenant.
        #
        # **E nao apaga em nenhuma das duas.** Em `offer_terms` apagar e
        # escrever `deleted_at` (o secao 5.6 manda soft delete nas ofertas), e
        # em `price_quotes` uma cotacao emitida e **prova** do preco que o dono
        # deu: revoga-se pelo `estado`, e um `DELETE` concedido tornava-a
        # reescrivel sem deixar rasto. Quem apaga e o `kamba_batch`, que e o
        # papel da retencao (KAM-071).
        #
        # O `kamba_audit` nao ganha nada: ele le o `audit_log`, e o que este
        # modulo escreve la ja o cobre. Um `SELECT` no catalogo dava-lhe o
        # preco de cada loja, que nao e o que ele audita.
        "offer_terms": {
            # **Sem `UPDATE` aqui, e nao e falta:** o `UPDATE` das duas tabelas
            # e **por coluna** (ver a revisao `0028`), e o
            # `has_table_privilege` so ve concessoes de tabela. O que prende as
            # colunas e o `test_o_update_e_por_coluna_nas_duas` de
            # `db/tests_produtos/test_contrato.py`, que as percorre uma a uma
            # nos dois sentidos.
            "kamba_app": {"SELECT", "INSERT"},
            "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            "kamba_audit": set(),
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
        # O `UPDATE` da cotacao e **por coluna**, e so o `estado` — ver a
        # revisao `0028`.
        "price_quotes": {
            "kamba_app": {"SELECT", "INSERT"},
            "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            "kamba_audit": set(),
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
        # ------------------------------------------------- KAM-044 (0030)
        #
        # As cinco das encomendas. **Sem `UPDATE` de tabela em tres delas**, e
        # nao e falta: o `UPDATE` da `orders_mirror`, do `order_intents` e do
        # `order_reconciliation_issues` e **por coluna** (ver a revisao `0030`),
        # e o `has_table_privilege` so ve concessoes de tabela — quem as prende
        # uma a uma e o `test_o_update_e_por_coluna` da classe
        # `TestPrivilegiosPorColuna` de `db/tests_encomendas/test_isolamento.py`
        # — **o caminho que esta nota dava nao existia**, e foi a revisao
        # adversarial que o mediu.
        "orders_mirror": {
            "kamba_app": {"SELECT", "INSERT"},
            "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            "kamba_audit": set(),
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
        "order_intents": {
            "kamba_app": {"SELECT", "INSERT"},
            "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            "kamba_audit": set(),
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
        # KAM-045 (0033): a reserva de stock.
        #
        # **Sem `DELETE` para o `kamba_app`**, e e o criterio 6 por construcao:
        # uma reserva nao se apaga, **liberta-se com motivo**. Apagar era perder
        # a razao pela qual o stock voltou, que e o que a reconciliacao da regra
        # 4 do §10.3 le. O `UPDATE` que ele tem e **por coluna** — oito, no
        # `GRANT UPDATE (...)` da revisao —, e esta matriz ve o privilegio de
        # tabela e nao a lista de colunas: a lista esta no `test_contrato` do
        # `tests_produtos` para a oferta e no inventario para esta.
        #
        # O `kamba_batch` tem os quatro: e ele que varre (o *job* do criterio 4)
        # e que semeia as baterias de isolamento, com `BYPASSRLS` por atributo.
        "stock_reservations": {
            # **Sem `UPDATE` aqui, e isso nao e uma omissao: e o que o `GRANT`
            # por coluna significa nesta matriz.** A revisao concede
            # `UPDATE (estado, motivo, expira_at, ...)` — oito colunas —, e o
            # `has_table_privilege(..., 'UPDATE')` que esta matriz le devolve
            # **false** para um privilegio so de coluna. E exactamente como o
            # `orders_mirror` esta modelado, pela mesma razao: a `0030` tambem
            # lhe da `UPDATE` por coluna e esta matriz diz `{SELECT, INSERT}`.
            #
            # Quem ve a lista de colunas e o inventario e o `test_contrato` do
            # `tests_produtos`, que leem o `has_column_privilege`. Medido: pôr
            # `UPDATE` aqui da `AssertionError: False != True`.
            "kamba_app": {"SELECT", "INSERT"},
            "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            "kamba_audit": set(),
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
        # **`SELECT` e `INSERT` e mais nada, nos dois papeis**, e e o criterio 6
        # a letra («so `INSERT` para `kamba_app`»). O `kamba_batch` tambem nao
        # tem `UPDATE` nem `DELETE` aqui, ao contrario das outras quatro: o
        # `deny_mutation` da `0029` recusa-os de qualquer forma, e conceder um
        # privilegio que um *trigger* anula escrevia no catalogo uma permissao
        # que nao existe.
        #
        # O `SELECT` do `kamba_app` **nao e um alargamento**: e o *trigger*
        # diferido `order_estado_exige_log` que le esta tabela, como invocador,
        # e sem o privilegio nenhuma transicao confirmava. Vale tambem a razao
        # que a `0004` escreveu para o outbox — sem um papel sujeito a RLS que a
        # leia, a politica nunca e exercida.
        "order_state_log": {
            "kamba_app": {"SELECT", "INSERT"},
            "kamba_batch": {"SELECT", "INSERT"},
            "kamba_audit": set(),
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
        # O grafo e **referencia**: a aplicacao le-o e quem o escreve e uma
        # revisao. As transicoes validas de um sistema nao sao configuracao de
        # tenant, e um `INSERT` concedido aqui deixava o caminho da aplicacao
        # declarar valida uma transicao que o §6.2 nao tem.
        "order_state_graph": {
            "kamba_app": {"SELECT"},
            "kamba_batch": {"SELECT"},
            "kamba_audit": set(),
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
        "order_reconciliation_issues": {
            "kamba_app": {"SELECT", "INSERT"},
            "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            "kamba_audit": set(),
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
    }
)

#: O `kamba_agr` (KAM-026) nao tem privilegio nenhum em `platform`, em nenhuma
#: tabela — e isso **e** o criterio 4 do bloco, nao uma omissao.
#:
#: Entra por aqui e nao nas nove matrizes a mao por duas razoes. A entrada e a
#: mesma nas nove, e nove copias de `set()` escondem a afirmacao em vez de a
#: fazerem; e o dia em que ele ganhar privilegio em alguma, a excepcao aparece
#: contra **esta** linha, que diz que ele nao tem nenhum. A nove copias, a
#: excepcao era indistinguivel de uma distraccao.
#:
#: O que o `lg` lhe concede esta na revisao `0020` e prova-se na bateria do
#: KAM-026, nao aqui: esta matriz e de `platform`.
#:
#: **A revisao `0038` (KAM-070) nao e excepcao a esta linha, e por decisao.** Uma
#: primeira versao dela dava ao `kamba_agr` `SELECT` na `dsar_requests` e
#: `SELECT, INSERT` na `erasure_ledger`, porque o criterio 3 daquele bloco nomeia
#: o AGR como um dos seis consumidores do `privacy.erasure_requested`. **Saiu.**
#: Afrouxar o criterio de outro ticket a partir de um terceiro nao e decisao de
#: quem implementa o terceiro, e «o dia em que ele ganhar privilegio em alguma»
#: e um dia que o KAM-026 decide, nao este.
#:
#: O consumidor do AGR escreve a linha do ledger pela ligacao de **aplicacao**,
#: que tem `SELECT, INSERT` nas duas tabelas. A fronteira continua a ser a que
#: esta linha afirma: o `kamba_agr` alcanca o `lg` e mais nada, e aplicar um
#: apagamento no `platform` nao e trabalho de *checkpointer*.
PAPEIS_SEM_NADA_EM_PLATFORM = ("kamba_agr",)

#: O `kamba_pay_hooks` (KAM-053) nao tem privilegio nenhum em **nenhuma** das
#: tabelas declaradas acima — tem-nos so nas da revisao `0029`, que se declaram
#: depois desta compreensao.
#:
#: **Numa constante propria e nao dentro do `PAPEIS_SEM_NADA_EM_PLATFORM`**, e a
#: diferenca nao e estilo: aquela linha afirma «este papel nao alcanca o
#: `platform`», que e o criterio 4 do KAM-026 e continua a ser verdade; esta
#: afirma «este papel alcanca o `platform` **so** pelas tabelas de pagamento».
#: Juntar os dois numa so fazia a primeira afirmacao falsa a partir do momento
#: em que a segunda tabela aparecesse, e a excepcao do `kamba_pay_hooks` ficava
#: indistinguivel de uma distraccao.
#:
#: O que ele alcanca esta tres blocos abaixo, e e pouco de proposito: `SELECT,
#: INSERT` e `UPDATE` de quatro colunas no `payment_callbacks_inbox` — que nao
#: tem `tenant_id` —, `SELECT` de sete colunas na `payment_accounts` (em
#: `COLUNAS_POR_PAPEL`, porque um `GRANT` por coluna nao aparece nesta matriz),
#: e nada na `payment_charges`, no `payment_events` nem na `payment_outbox_map`
#: — e as quatro entram em `TABELAS_COM_MATRIZ_DE_COLUNA`, que e onde a
#: ausencia se afirma coluna a coluna, para os oito papeis.
#: **Nao executa a porta do ledger**: ele corre antes de haver contexto de
#: tenant, a RLS recusar-lhe-ia a cobranca de qualquer forma, e dar-lhe
#: `EXECUTE` era deixar na matriz um privilegio que nao se pode usar.
PAPEIS_SO_NAS_TABELAS_DE_PAGAMENTO = ("kamba_pay_hooks",)

ESPERADO_POR_TABELA = {
    tabela: dict(
        por_papel,
        **{
            p: set()
            for p in (
                *PAPEIS_SEM_NADA_EM_PLATFORM,
                *PAPEIS_SO_NAS_TABELAS_DE_PAGAMENTO,
            )
        },
    )
    for tabela, por_papel in ESPERADO_POR_TABELA.items()
}


def _pagamentos(**por_papel: set[str]) -> dict[str, set[str]]:
    """Matriz de uma tabela da revisao `0029` (KAM-053).

    Helper proprio e nao o `_uso` nem o `_auditoria`, e a razao e o papel novo:
    as duas familias acima foram escritas antes de o `kamba_pay_hooks` existir e
    nao o nomeiam, e as quatro tabelas desta revisao sao as unicas do esquema em
    que ele aparece com algo. Declara-se **depois** da compreensao do
    `PAPEIS_SO_NAS_TABELAS_DE_PAGAMENTO`, que e o que faz dele o zero em todas
    as outras — pela mesma forma que o `_agenda` do `servicos`.

    Omissoes: ninguem tem nada, e o que cada papel tem escreve-se por extenso em
    cada tabela. **O `kamba_migrator` tem tudo porque e o dono**, como em todas
    as matrizes, e isso nao mostra o *append-only* do ledger: quem o impoe e o
    `deny_mutation` com `ENABLE ALWAYS`, que esta bateria nao ve e que recusa
    tambem ao dono e ao superutilizador.
    """
    return {
        "kamba_app": set(),
        "kamba_batch": set(),
        "kamba_resolver": set(),
        "kamba_identity": set(),
        "kamba_audit": set(),
        "kamba_agr": set(),
        "kamba_pay_hooks": set(),
        "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
        "public": set(),
        **por_papel,
    }


ESPERADO_POR_TABELA.update(
    {
        # ------------------------------------------------- KAM-053 (0029)
        #
        # **Ninguem tem `UPDATE` em `payment_charges`, e e a barreira que o DoD
        # do bloco mede.** O `estado` muda **so** pela projeccao da
        # `append_payment_event`, que e `SECURITY DEFINER` e corre como o dono.
        # Com `UPDATE` concedido a qualquer papel havia um caminho para escrever
        # `paga` sem passar pela porta — isto e, o ticket inteiro deixava de ter
        # objecto. A ausencia aqui nao e uma folga a preencher: e a afirmacao.
        #
        # **Esta linha so a afirma a meias, e e por isso que a tabela esta
        # tambem em `TABELAS_COM_MATRIZ_DE_COLUNA`:** o
        # `has_table_privilege(..., 'UPDATE')` devolve `false` com ou sem um
        # `GRANT UPDATE (estado)` por coluna, pelo que a barreira caia por um
        # `GRANT` de uma palavra que esta matriz nao ve. E ali que ela se
        # afirma, coluna a coluna e nos dois sentidos.
        #
        # **O `kamba_app` tem `INSERT`, ao contrario da `payment_accounts` da
        # `0027`.** Uma cobranca nasce num turno de conversa (o `createOrder` do
        # COM) e uma conta de pagamento nasce no onboarding de retaguarda — e e
        # essa a diferenca. O que prende a escrita sao duas coisas que esta
        # matriz nao ve: o `WITH CHECK` da `tenant_iso`, que prende o
        # `tenant_id` ao contexto, e o *trigger* `assert_beneficiary` (G-1), que
        # prende o beneficiario e recusa **antes** da politica.
        #
        # **O `kamba_batch` apaga e o `kamba_app` nao**, pela regra que a `0025`
        # escreveu e a `0027` repetiu: quem apaga e o papel da retencao
        # (KAM-071) e o semeador das baterias. **O `kamba_audit` le**, porque
        # «quanto se pediu e em que estado ficou» e pergunta de auditoria.
        #
        # **O `kamba_pay_hooks` nao tem nada aqui**, e isso e o secao 5.1: ele
        # grava a entrega e devolve 2xx; quem toca na cobranca e o *worker*, que
        # corre como `kamba_app` com o contexto resolvido.
        "payment_charges": _pagamentos(
            kamba_app={"SELECT", "INSERT"},
            kamba_batch={"SELECT", "INSERT", "DELETE"},
            kamba_audit={"SELECT"},
        ),
        # O inbox. **O `kamba_app` nao entra, e e a unica tabela de `platform` em
        # que isso acontece por causa da RLS que ela nao tem**: sem `tenant_id`
        # nao ha politica, pelo que um `SELECT` do papel da aplicacao lia os
        # callbacks de **todas** as PMEs. O que a isola e o papel, e nao a
        # politica — e por isso o papel e estreito.
        #
        # **O `UPDATE` nao esta nesta matriz e existe**: e por coluna, quatro
        # colunas, e esta em `COLUNAS_POR_PAPEL`. O que fica de fora delas e a
        # afirmacao — o `body`, o `body_hash`, os `headers`, o `source_ip` e o
        # `recebido_at` nao se reescrevem, e e isso que faz do inbox uma prova
        # em vez de um registo de trabalho.
        #
        # **O `kamba_pay_hooks` insere e o `kamba_batch` nao**, e e deliberado:
        # quem grava a entrega e quem a recebe. O lote le, marca o desfecho do
        # que processou e apaga na retencao.
        #
        # O `kamba_audit` nao ganha nada: ele le o `audit_log` e o ledger, e o
        # corpo cru de um callback nao e o que ele audita — e a mesma razao
        # pela qual ele nao le o catalogo da `0028`.
        "payment_callbacks_inbox": _pagamentos(
            kamba_pay_hooks={"SELECT", "INSERT"},
            kamba_batch={"SELECT", "DELETE"},
        ),
        # O ledger. **Ninguem tem `INSERT`, e e metade da porta**: sem
        # privilegio, um `INSERT` directo falha com `42501` antes de chegar a um
        # `CHECK`. A outra metade e o `deny_mutation`, que recusa
        # `UPDATE`/`DELETE`/`TRUNCATE` **a todos** incluindo ao dono e ao
        # superutilizador — e e a razao de a imutabilidade nao ser so uma matriz
        # de privilegios. Esta linha prende o que a matriz **pode** prender: que
        # nao apareca um `INSERT` concedido a alguem.
        #
        # Os tres que leem leem por tres razoes diferentes: o `kamba_app`
        # porque o *worker* precisa de ver o que ja registou (a sequencia, o
        # ultimo estado), o `kamba_batch` porque a reconciliacao do secao 8 e
        # dele, e o `kamba_audit` porque «esta cadeia esta intacta» e uma
        # pergunta de auditoria.
        #
        # O `kamba_pay_hooks` **nao** le: ele nao sabe de que tenant e o
        # callback no instante em que o grava, e um papel sem contexto a ler um
        # ledger com RLS lia zero linhas — um privilegio que nao se pode usar.
        "payment_events": _pagamentos(
            kamba_app={"SELECT"},
            kamba_batch={"SELECT"},
            kamba_audit={"SELECT"},
        ),
        # O mapeamento `(tipo_evento, authn_method) -> tipo EVT`. Configuracao
        # **global**, como a `evt_subscricoes` da `0004`, e com a mesma forma de
        # matriz: a aplicacao le (e ela que decide se publica evento de dominio)
        # e o lote escreve, porque encher a tabela e provisionamento.
        #
        # **Fica vazia nesta revisao** — o conteudo e do KAM-055 —, e a matriz
        # declara-se igual: um privilegio que so se concede quando a tabela
        # tiver linhas e um privilegio que ninguem reve.
        "payment_outbox_map": _pagamentos(
            kamba_app={"SELECT"},
            kamba_batch={"SELECT", "INSERT", "DELETE"},
        ),
    }
)


def _agenda(*privilegios_da_app: str) -> dict[str, set[str]]:
    """Matriz de uma tabela do `servicos` (KAM-047, revisao `0025`).

    **O `kamba_app` escreve nesta agenda, e isso distingue este esquema do
    `dat`.** Ali o papel da aplicacao insere e nao le, porque quem produz um
    registo de custo nao e quem o audita. Aqui a agenda **e** o estado de
    negocio que a TLS le e escreve a cada turno: sem `SELECT` nao havia
    disponibilidade para calcular, e e a RLS que o limita as linhas do tenant —
    o que faz dela uma barreira exercida e nao decoracao.

    **Quatro papeis nao tem nada, nem `USAGE` no esquema**, e a ausencia e a
    afirmacao: o `kamba_resolver` resolve canais, o `kamba_identity` guarda o
    cofre de contactos, o `kamba_audit` le a `audit_log`, e o `kamba_agr` guarda
    o estado das conversas. Nenhum deles tem razao para chegar a agenda de
    ninguem, e e a mesma escolha que o KAM-026 fez ao deixar o `kamba_agr` sem
    `USAGE` no `platform`.

    **O `kamba_batch` tem `DELETE` e o `kamba_app` nao.** Cancelar e um `UPDATE`
    do estado — a restricao de exclusao e parcial, pelo que a linha deixa de
    ocupar o intervalo sem ser apagada —, e um `DELETE` concedido a aplicacao
    tornava a agenda reescrevivel sem deixar rasto. Quem apaga e o papel da
    retencao (KAM-071) e o semeador das baterias de isolamento.
    """
    return {
        "kamba_app": set(privilegios_da_app),
        "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        "kamba_resolver": set(),
        "kamba_identity": set(),
        "kamba_audit": set(),
        "kamba_agr": set(),
        # KAM-053: a mao e nao pela compreensao do
        # `PAPEIS_SO_NAS_TABELAS_DE_PAGAMENTO`, que corre **antes** deste
        # helper — a mesma razao pela qual o `kamba_agr` tambem esta escrito
        # aqui. O papel dos *webhooks* de pagamento nao tem `USAGE` no
        # `servicos`, pelo que nao alcanca a agenda de ninguem: o que ele
        # atende e um callback de pagamento, e uma marcacao nao e um pagamento.
        "kamba_pay_hooks": set(),
        "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
        "public": set(),
    }


ESPERADO_POR_TABELA.update(
    {
        # O catalogo e **so de leitura** para a aplicacao: quem cria a agenda de
        # uma PME e o onboarding de retaguarda (KAM-091). E a mesma razao pela
        # qual a `0007` tirou `INSERT` em `entitlements` a este papel — com
        # `WITH CHECK (tenant_id = app.tenant_id)` um tenant criava as proprias
        # linhas, e aqui isso significava inventar recursos para abrir
        # intervalos que o dono nunca disponibilizou.
        "services": _agenda("SELECT"),
        "resources": _agenda("SELECT"),
        "availability_rules": _agenda("SELECT"),
        # **`SELECT, INSERT` e nao `UPDATE`.** O `UPDATE` existe, e e por
        # coluna: `has_table_privilege(..., 'UPDATE')` devolve `false` com ou
        # sem `GRANT UPDATE (coluna)`, e por isso a matriz de coluna cobre esta
        # tabela (ver `TABELAS_COM_MATRIZ_DE_COLUNA`).
        "bookings": _agenda("SELECT", "INSERT"),
    }
)

ESPERADO_POR_TABELA.update(
    {
        # ------------------------------------------------- KAM-054 (0032)
        #
        # **A aplicacao le as quatro e nao escreve nenhuma.** E a mesma escolha
        # da `payment_accounts` na `0027` — «quem provisiona nao e um turno de
        # conversa» —, e aqui vale duas vezes, porque em duas delas o `INSERT`
        # desfazia uma guarda e nao so uma convencao:
        #
        #   payment_confirmers    com `INSERT`, um tenant acrescentava-se a si
        #     proprio a lista de quem pode confirmar: a guarda do M-1 era um
        #     `INSERT`. O `WITH CHECK (tenant_id = app.tenant_id)` da
        #     `tenant_iso` **nao** o impedia — a linha que ele criava era do
        #     proprio tenant, que e precisamente o problema. E a mesma escalada
        #     por outro verbo que a `0007` fechou nos `entitlements`
        #   manual_confirmations com `INSERT`, escrevia-se uma
        #     `declaracao_cliente` com o `actor_contact_id` a escolha — e a
        #     `manual_confirmar` descobre quem e o cliente **lendo** essa fase.
        #     Quem a pudesse escrever escolhia quem o cliente e, o que abre a
        #     fraude mais obvia deste caminho: o cliente a confirmar o proprio
        #     pagamento
        #   refund_cases         com `INSERT`, abria-se um caso de reembolso sem
        #     reversao e sem evento no ledger — a «abuso de reembolso» do secao 9
        #   fraud_signals        com `INSERT`, quem e vigiado escrevia no registo
        #     de vigilancia
        #
        # O que a aplicacao precisa de escrever, escreve pelas quatro funcoes
        # `manual_*`, que sao `SECURITY DEFINER` e tem as regras dentro. **O que
        # se prova nesta matriz, portanto, nao e que a politica recusa: e que o
        # privilegio nem existe**, que e mais forte — nao depende de a politica
        # estar certa.
        #
        # **O `kamba_batch` escreve duas e nao as quatro.** O ciclo de vida que
        # corre fora de um turno e a lista de confirmadores (o onboarding de
        # retaguarda, KAM-091) e o fecho de um caso de reembolso, que a PME
        # executa fora da plataforma e alguem tem de registar. Nas outras duas
        # nao tem `UPDATE` nenhum: sao **registos**, e um registo que se corrige
        # nao e um registo.
        #
        # O `UPDATE` dos dois que o tem **nao esta nesta matriz**: e por coluna,
        # e por isso as duas tabelas entram em `TABELAS_COM_MATRIZ_DE_COLUNA`.
        #
        # **O `kamba_audit` le as quatro**, e e a primeira familia em que ele
        # tem tudo: quem confirmou, com que valor declarado, que limite retido e
        # que caso aberto sao exactamente as perguntas de uma auditoria de
        # dinheiro. **O `kamba_pay_hooks` nao tem nada**: um callback nao toca na
        # via humana, e e esse o ponto do ADR-013.
        "payment_confirmers": _pagamentos(
            kamba_app={"SELECT"},
            kamba_batch={"SELECT", "INSERT", "DELETE"},
            kamba_audit={"SELECT"},
        ),
        "manual_confirmations": _pagamentos(
            kamba_app={"SELECT"},
            kamba_batch={"SELECT"},
            kamba_audit={"SELECT"},
        ),
        "refund_cases": _pagamentos(
            kamba_app={"SELECT"},
            kamba_batch={"SELECT"},
            kamba_audit={"SELECT"},
        ),
        "fraud_signals": _pagamentos(
            kamba_app={"SELECT"},
            kamba_batch={"SELECT"},
            kamba_audit={"SELECT"},
        ),
    }
)

ESPERADO_POR_TABELA.update(
    {
        # ------------------------------------------------- KAM-091 (0034)
        #
        # O estado da saga de provisioning. **Os nove papeis por extenso e nao
        # um helper**: esta entrada declara-se depois da compreensao que injecta
        # o `PAPEIS_SEM_NADA_EM_PLATFORM` e o
        # `PAPEIS_SO_NAS_TABELAS_DE_PAGAMENTO`, pelo que nao herda os zeros
        # deles — e o `_pagamentos` nao serve, porque e o helper das quatro
        # tabelas da `0029` e usa-lo aqui dizia que esta era uma delas.
        #
        # **`SELECT, INSERT` para o `kamba_app`, e o `UPDATE` que ele tem e por
        # coluna** — seis, no `GRANT UPDATE (...)` da revisao. Esta matriz le o
        # `has_table_privilege(..., 'UPDATE')`, que devolve **false** para um
        # privilegio so de coluna; a lista de colunas esta no
        # `COLUNAS_POR_PAPEL`, e por isso a tabela entra tambem em
        # `TABELAS_COM_MATRIZ_DE_COLUNA`. E exactamente como o `bookings` esta
        # modelado, e pela mesma razao.
        #
        # **E a aplicacao escreve aqui, ao contrario das quatro da `0032`.** A
        # razao esta nos *Testes Requeridos* do bloco: «a saga corre sob
        # `app.tenant_id` do caso», logo e um papel sujeito a RLS que grava o
        # estado dos passos — nao um *job* de plataforma.
        #
        # **Sem `DELETE` para o `kamba_app`**, e e o criterio 3 por construcao:
        # um passo nao se apaga, compensa-se. Apagar a linha era perder a
        # distincao entre «foi desfeito» e «nunca correu», que e a razao pela
        # qual o `compensado` existe como estado proprio — e sem ela a
        # reconciliacao nocturna classificava um recurso compensado como
        # `externo_em_falta` e voltava a cria-lo.
        #
        # O `kamba_batch` tem os quatro: e ele que corre a reconciliacao, que
        # atravessa tenants (`BYPASSRLS` por atributo), e que semeia as baterias
        # de isolamento.
        "provisioning_step": {
            "kamba_app": {"SELECT", "INSERT"},
            "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_audit": set(),
            "kamba_agr": set(),
            "kamba_pay_hooks": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
    }
)

#: KAM-069 (revisao `0036`): os destinos de transferencia.
#:
#: **O `kamba_app` le e nao escreve, e e a diferenca que importa nesta tabela.**
#: Autorizar um destino e um acto humano com papelada arquivada — contrato,
#: retencao zero, nao-treino, numero de procedimento da APD — e nao uma escrita
#: de um processo que serve conversas. Sem `INSERT` nem `UPDATE`, a *porta* de
#: destinos nao consegue autorizar-se a si propria: um defeito no servico que
#: serve o turno nao pode abrir um destino.
#:
#: E ao contrario do `provisioning_step` logo acima, aqui **nao** ha matriz por
#: coluna: nao se conceder `UPDATE` nenhum e mais forte do que conceder seis
#: colunas, pelo que esta tabela nao entra em `TABELAS_COM_MATRIZ_DE_COLUNA` —
#: nao ha `GRANT UPDATE (coluna)` onde uma coluna a mais se pudesse esconder.
#:
#: **O `kamba_audit` le**, e entra porque «para onde foram os dados deste
#: tenant» e uma pergunta de auditoria: e ele que le a vista `v_transfer_audit`,
#: que com `security_invoker` exige privilegio nas duas tabelas por baixo. Nao o
#: poe acima da RLS — o `kamba_audit` **nao** tem `BYPASSRLS` (so o
#: `kamba_batch` tem), pelo que ve o tenant do seu contexto e as linhas globais.
#:
#: O `kamba_batch` tem os quatro: e ele que escreve um destino autorizado quando
#: a APD responder, e que semeia as baterias de isolamento.
ESPERADO_POR_TABELA.update(
    {
        "tenant_destinations": {
            "kamba_app": {"SELECT"},
            "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_audit": {"SELECT"},
            "kamba_agr": set(),
            "kamba_pay_hooks": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
    }
)

#: KAM-070 (revisao `0038`): os direitos do titular.
#:
#: **Os nove papeis por extenso nas duas, pela razao do `provisioning_step`**:
#: estas entradas declaram-se depois da compreensao que injecta o
#: `PAPEIS_SEM_NADA_EM_PLATFORM` e o `PAPEIS_SO_NAS_TABELAS_DE_PAGAMENTO`, pelo
#: que nao herdam os zeros deles — e aqui isso nao e so forma, e o ponto
#: seguinte.
#:
#: **O `kamba_agr` continua com zero nas duas**, e e a emenda que a revisao do
#: lote obrigou. A nota do `PAPEIS_SEM_NADA_EM_PLATFORM` acima afirma «em nenhuma
#: tabela», e essa frase **e** o criterio 4 do KAM-026: dar-lhe aqui `SELECT` e
#: `INSERT` tornava-a falsa a partir desta revisao, e quem decide afrouxar o
#: criterio de um ticket nao e quem implementa outro.
#:
#: O escopo `agr` do criterio 3 do KAM-070 nao fica sem aplicador por isso: o
#: consumidor do AGR escreve a sua linha pela ligacao de **aplicacao**, que tem
#: `SELECT, INSERT` nas duas. O que ele nao faz e alcancar o `platform` pelo
#: papel do *checkpointer*.
ESPERADO_POR_TABELA.update(
    {
        "dsar_requests": {
            "kamba_app": {"SELECT", "INSERT"},
            "kamba_batch": {"SELECT"},
            "kamba_resolver": set(),
            "kamba_identity": {"SELECT"},
            "kamba_audit": {"SELECT"},
            "kamba_agr": set(),
            "kamba_pay_hooks": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
        "erasure_ledger": {
            "kamba_app": {"SELECT", "INSERT"},
            "kamba_batch": {"SELECT", "INSERT"},
            "kamba_resolver": set(),
            "kamba_identity": {"SELECT", "INSERT"},
            "kamba_audit": {"SELECT"},
            "kamba_agr": set(),
            "kamba_pay_hooks": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
    }
)

#: O aceite contratual (KAM-090, revisao `0040`). **Ninguem tem `UPDATE` nem
#: `DELETE` em nenhuma das duas**, e e o que as faz *append-only*.
#:
#: A versao publicada **publica-se pelo lote** e le-se por todos os que a
#: servem ou auditam: dar `INSERT` a aplicacao deixava o caminho que serve
#: clientes publicar um texto juridico — a razao da `consent_texts`. A prova
#: **escreve-se pela aplicacao**, que serve o ecra de aceite, e passa pelo
#: *trigger* que exige a versao vigente; o lote **le-a** porque e ele que muda
#: `tenants.estado`, e o gate corre com os olhos de quem invoca. O `kamba_agr`
#: nao entra, pela razao do `PAPEIS_SEM_NADA_EM_PLATFORM`.
ESPERADO_POR_TABELA.update(
    {
        "contract_document": {
            "kamba_app": {"SELECT"},
            # `INSERT` por coluna, e por isso nao aparece aqui: esta em
            # `COLUNAS_POR_PAPEL`, sem o `publicado_em`.
            "kamba_batch": {"SELECT"},
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_audit": {"SELECT"},
            "kamba_agr": set(),
            "kamba_pay_hooks": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
        "contract_acceptance": {
            "kamba_app": {"SELECT", "INSERT"},
            "kamba_batch": {"SELECT"},
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_audit": {"SELECT"},
            "kamba_agr": set(),
            "kamba_pay_hooks": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
    }
)

#: O caso de onboarding e a verificacao K1 (KAM-087, revisao `0043`). Os
#: `UPDATE` sao **por coluna** e nao aparecem nesta matriz de tabela: o
#: `kamba_app` altera a `fase`, as `flags`, o `owner_active_seconds` e o
#: `preflight`; o lote altera a `fase`, as `flags`, o `preflight` e o
#: `activo_at`, e na verificacao o `resultado`, o `score`, as `flags` e o
#: `extraido_enc`. **Ninguem apaga**, e a aplicacao **nao alcanca** o
#: `kyc_check`: as marcas sao o motivo interno do criterio 7.
ESPERADO_POR_TABELA.update(
    {
        "onboarding_case": {
            "kamba_app": {"SELECT", "INSERT"},
            "kamba_batch": {"SELECT"},
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_audit": {"SELECT"},
            "kamba_agr": set(),
            "kamba_pay_hooks": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
        "kyc_check": {
            "kamba_app": set(),
            "kamba_batch": {"SELECT", "INSERT"},
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_audit": {"SELECT"},
            "kamba_agr": set(),
            "kamba_pay_hooks": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
    }
)

#: O registo da purga (KAM-071, revisao `0042`). **Append-only por privilegio,
#: e por mais nada**: o lote escreve e le, a auditoria le, e ninguem tem
#: `UPDATE` nem `DELETE` — nem o lote, que e quem purga e por isso o ultimo que
#: devia poder apagar a prova de que purgou. A aplicacao nao alcanca a tabela.
ESPERADO_POR_TABELA.update(
    {
        "purge_log": {
            "kamba_app": set(),
            "kamba_batch": {"SELECT", "INSERT"},
            "kamba_resolver": set(),
            "kamba_identity": set(),
            "kamba_audit": {"SELECT"},
            "kamba_agr": set(),
            "kamba_pay_hooks": set(),
            "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
            "public": set(),
        },
    }
)

#: (papel, tabela, privilegio) -> colunas concedidas **por coluna** nas tabelas
#: da revisao 0003. O que nao esta aqui nao tem privilegio de coluna nenhum.
COLUNAS_POR_PAPEL = {
    # KAM-070: **duas** colunas, e os dois papeis que as tem concedidas tem a
    # mesma lista — o `kamba_app` fecha o pedido que recebeu, e o `kamba_batch`
    # varre prazos e aplica o escopo `dat`.
    #
    # O que fica **fora** e o que define o pedido, e cada uma por uma razao:
    # mudar o `tipo` de um pedido em curso e um pedido novo, mudar o
    # `contact_id` e dar os dados de um titular a outro, e o `prazo_interno_at`
    # tambem nao entra — um prazo legal que se pode empurrar nao e um prazo. O
    # `recebido_at` e quando chegou.
    #
    # E o que uma coluna a mais daria e a razao medida do KAM-015 com outro
    # nome: um `GRANT UPDATE (prazo_interno_at)` deixava quem corre o
    # varrimento adiar o prazo do pedido em vez de o cumprir, e o alerta dos 20
    # dias do criterio 8 nunca disparava. Nenhuma matriz de tabela ve isso — o
    # `has_table_privilege(..., 'UPDATE')` devolve `false` com ou sem o `GRANT`
    # por coluna.
    ("kamba_app", "dsar_requests", "UPDATE"): {"estado", "concluido_at"},
    ("kamba_batch", "dsar_requests", "UPDATE"): {"estado", "concluido_at"},
    # KAM-054: tres colunas em cada uma das duas, e sao o ciclo de vida.
    #
    # No `payment_confirmers`, as que ficam **fora** sao o `tenant_id` e o
    # `contact_id` — a chave —, e isso e a propriedade: mover um confirmador
    # de tenant ou de contacto e reatribuir quem pode confirmar, e nao um
    # `UPDATE`. Retirar um funcionario e `ativo = false`.
    #
    # Na `refund_cases`, ficam fora o `tenant_id`, o `order_id`, o
    # `charge_id`, o `motivo`, o `valor_minor` e o `criado_at`: o montante e
    # a razao de um caso sao o que ele **e**, e a reescrita deles e a «abuso
    # de reembolso» da tabela do secao 9.
    ("kamba_batch", "payment_confirmers", "UPDATE"): {
        "papel", "pode_segunda_aprovacao", "ativo",
    },
    ("kamba_batch", "refund_cases", "UPDATE"): {
        "estado", "prova_ref", "fechado_at",
    },
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
    # KAM-090: o lote publica as versoes **sem** o `publicado_em` nem o
    # `document_id`. A data de publicacao e a omissao `now()`, e e isso que da
    # dentes ao `contract_document_sem_retroactivo_ck`: com a coluna concedida,
    # o lote publicava hoje um DPA que «vigorava» ha um ano — medido pela
    # revisao adversarial.
    ("kamba_batch", "contract_document", "INSERT"): {
        "tipo", "versao", "sha256", "conteudo", "vigente_desde",
    },
    # KAM-028: as dezoito colunas que quem invoca escreve — todas menos o `id`
    # (identidade) e o `ts` (`DEFAULT now()`). O `ts` fica de fora mesmo com o
    # `DEFAULT` a reescreve-lo na mesma: uma coluna que nenhum chamador pode
    # escrever e uma coluna que nenhum chamador tenta escrever, e o instante de
    # uma linha de auditoria nao e do chamador.
    ("kamba_app", "tool_audit", "INSERT"): {
        "tenant_id", "contact_id", "conversation_id", "turn_id", "run_id",
        "vertical", "graph_version", "tool", "tool_version", "klass",
        "args_hash", "args_redacted", "idempotency_key", "status", "error_code",
        "result_hash", "fact_ids", "latency_ms",
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
    # KAM-014 e KAM-018: **quatro** colunas, e eram duas. As duas da `0009` sao
    # as que o CHR escreve em cada entrada — a janela de 24 h abre-se com a
    # mensagem que chega. As outras duas chegam com a revisao `0016`, e sao as
    # que a maquina de modos escreve: a `0009` deixou-as de fora de proposito
    # («as transicoes sao KAM-018, e e esse ticket que pede o privilegio»), e o
    # protocolo que ela exigia existe agora (`docs/modos-conversa.md`).
    #
    # **As quatro que continuam fora sao o que importa**: `id`, `tenant_id`,
    # `contact_id` e `channel_id`. Alterar qualquer uma por esta via e
    # reescrever a identidade da conversa — mover uma conversa de contacto e de
    # canal —, e quem a reaponta numa fusao e o `kamba_identity`, dentro da
    # transaccao da fusao.
    ("kamba_app", "conversations", "UPDATE"): {
        "mode",
        "last_human_activity_at",
        "last_inbound_at",
        "window_expires_at",
    },
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
    # KAM-021. **Conjunto vazio, e e uma afirmacao e nao uma omissao:** a
    # `0014` nao concede `UPDATE` nenhum em `channel_quality_log` a
    # `kamba_app`. E a mesma forma que a `0011` usou para a
    # `handoff_accounts`, e o que ela prova e mais forte do que uma politica:
    # o privilegio **nem existe**, pelo que nao depende de a RLS estar certa.
    ("kamba_app", "channel_quality_log", "UPDATE"): set(),
    # KAM-022. **Dois conjuntos vazios, e sao o criterio 6 escrito em
    # privilegios:** a `0015` nao concede `UPDATE` nenhum nas duas tabelas a
    # `kamba_app`. Na `consent_event` porque uma prova append-only que se possa
    # corrigir nao e prova; na `consent_texts` porque editar o texto de uma
    # versao ja mostrada era reescrever o que um cliente viu — e a `hash` da
    # linha existe exactamente para se poder dizer que isso nao aconteceu.
    ("kamba_app", "consent_event", "UPDATE"): set(),
    ("kamba_app", "consent_texts", "UPDATE"): set(),
    # KAM-016. **Conjunto vazio, e e o desenho do ticket em privilegios:** a
    # `0017` nao concede `UPDATE` nenhum a `kamba_app`. Quem escreve esta tabela
    # e o `kamba_batch`, e nao e precaucao — sao tres consequencias medidas: o
    # contador `es_onboardings_7d` **atravessa tenants** e so corre com
    # `BYPASSRLS`; a compensacao do criterio 7 **apaga** a linha de
    # `tenant_channels` que o passo anterior criou, e `kamba_app` nao tem
    # `DELETE` em tabela nenhuma desde a `0001`; e o que protege a escrita passa
    # a ser a falta de privilegio, que e mais forte do que a politica recusar.
    ("kamba_app", "channel_onboarding", "UPDATE"): set(),
    # KAM-017. **Todas as colunas de estado, e nenhuma das tres chaves.** O
    # `id`, o `tenant_id` e o `channel_id` ficam de fora pela razao de sempre:
    # mover uma coexistencia de canal ou de tenant era entregar o estado de
    # sincronizacao de um negocio a outro, e a unicidade
    # `(tenant_id, channel_id)` deixava de significar o que significa. O
    # `criado_at` tambem: e registo.
    ("kamba_app", "channel_coexistence", "UPDATE"): {
        "estado",
        "passos_feitos",
        "iniciado_em",
        "prazo_em",
        "alertado_em",
        "concluido_em",
        "contactos_vistos",
        "mensagens_vistas",
        "meta_error_code",
        "ultimo_echo_em",
        "avisado_em",
        "motivo_desligamento",
        "desligado_em",
        "actualizado_at",
    },
    # KAM-115. **O desfecho, e nada mais.** Nem a `chave`, nem o `gatilho`, nem
    # o `episodio`, nem o `lembrete`, nem o `canal`: mover qualquer um deles era
    # fazer um aviso passar por outro, e a
    # `owner_notices_idempotencia_uq (tenant_id, chave, lembrete, canal)`
    # deixava de significar o que significa — o mesmo evento voltava a ser
    # avisado por se lhe ter mudado uma coluna da chave. O `criado_at` fica de
    # fora porque e registo, e e dele que os dois limites do criterio 4 contam.
    ("kamba_app", "owner_notices", "UPDATE"): {
        "estado",
        "entregue_at",
        "falha_motivo",
        "tentativas",
        "actualizado_at",
    },
    # KAM-115. O `endereco_enc` **esta aqui** e o `canal` nao: trocar o endereco
    # e o que o dono faz quando muda de e-mail (o KAM-086 escreve-o por este
    # papel), e trocar o canal era transformar um e-mail num painel — que nao
    # tem endereco. A verificacao e a invalidacao sao as duas escritas deste
    # ticket, e as duas sao colunas desta lista.
    ("kamba_app", "owner_contacts", "UPDATE"): {
        "endereco_enc",
        "verificado_at",
        "confirmacao_hash",
        "confirmacao_expira_em",
        "invalido_at",
        "motivo_invalido",
        "actualizado_at",
    },
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
    # KAM-029: as duas metades do protocolo do §6.3, e as duas sao **listas
    # exactas** por uma razao que o KAM-015 mediu e esta no
    # `TABELAS_COM_MATRIZ_DE_COLUNA`.
    #
    # No `INSERT` nao entra o `estado` — vem da omissao, `em_curso` — nem o
    # `created_at`: e por ele que a retencao apaga, e um chamador que o
    # escolhesse escolhia quando e que a sua reserva deixava de existir.
    #
    # No `UPDATE` so entram o desfecho e o resultado. **O `args_hash` nao, e e
    # a linha que importa deste ticket**: e a coluna que a recusa do criterio 3
    # compara, e quem a pudesse reescrever contornava a recusa que ela existe
    # para accionar. A `key` tambem nao: e a chave primaria, e reescreve-la era
    # transferir uma reserva de um carrinho para outro.
    ("kamba_app", "tool_idempotency", "INSERT"): {
        "key", "tenant_id", "tool", "args_hash",
    },
    ("kamba_app", "tool_idempotency", "UPDATE"): {"estado", "result"},
    # KAM-028, declarada pelo KAM-029 (divida 111). As **dezoito** colunas do
    # `COLUNAS_ESCRITAS_PELO_CHAMADOR` da revisao `0021`, e a lista e exacta: o
    # que importa aqui e o que **nao** esta nela — o `id` e o `ts`, que sao a
    # ordem e o instante da linha de auditoria, e nenhum dos dois e do chamador.
    #
    # **Nao ha `UPDATE` nem `DELETE` nenhum**, de ninguem, e a ausencia e a
    # afirmacao: a tabela e *append-only*, e quem o impoe sao as tres camadas da
    # `0021` (o `REVOKE`, o *trigger* e o `ENABLE ALWAYS`). Esta lista prende a
    # quarta coisa que elas nao veem, que e um privilegio de **coluna** a mais.
    ("kamba_app", "tool_audit", "INSERT"): {
        "tenant_id", "contact_id", "conversation_id", "turn_id", "run_id",
        "vertical", "graph_version", "tool", "tool_version", "klass",
        "args_hash", "args_redacted", "idempotency_key", "status", "error_code",
        "result_hash", "fact_ids", "latency_ms",
    },
    # KAM-030. As **catorze** colunas do `COLUNAS_DO_CHAMADOR` da revisao
    # `0023`, pela mesma razao com que a linha acima entrou: a
    # `dat.llm_call_log` tem `INSERT` **por coluna** e uma coluna a mais naquele
    # `GRANT` era invisivel em qualquer matriz de tabela. Foi o `fix` do
    # KAM-029 que fechou a divida 111 a declarar a vizinha, e esta tem a mesma
    # forma: declarar so uma delas era deixar a outra com o mesmo buraco.
    #
    # O que a lista prende e o que **nao** esta nela: o `id` e o `ts`. Um
    # `GRANT INSERT (ts)` punha o chamador a escolher o instante da sua propria
    # linha de custo — e com ele podia escrever uma chamada de hoje numa
    # particao de outro mes, o que faz o somatorio por *tenant* e a
    # `v_transfer_audit` do KAM-069 olharem para o sitio errado. Um
    # `GRANT INSERT (id)` deixava-o escolher a ordem.
    #
    # **Nao ha `UPDATE` nem `DELETE` nenhum, de ninguem**, e a ausencia e a
    # afirmacao: a tabela e *append-only*.
    ("kamba_app", "llm_call_log", "INSERT"): {
        "tenant_id", "trace_id", "vertical", "no_grafo", "papel",
        "graph_version", "modelo", "fornecedor", "tokens_in", "tokens_out",
        "tokens_cache", "custo_usd", "latencia_ms", "resultado",
    },
    # KAM-047: o `UPDATE` da aplicacao em `servicos.bookings` e **tres colunas**,
    # e o que fica de fora e a afirmacao. Nao inclui `tenant_id`, `contact_id`,
    # `service_id`, `resource_id`, `slot_id` nem `hold_id`: mudar qualquer um
    # deles era transformar a marcacao de um contacto na marcacao de outro, ou
    # reescrever a chave de idempotencia de uma confirmacao alheia. Nao inclui o
    # `inicio_at`/`fim_at`, e essa e a que importa mais — remarcar **e** cancelar
    # mais inserir, e um `UPDATE` do intervalo movia a linha de um intervalo para
    # outro sem passar pela restricao de exclusao do novo, que e precisamente a
    # barreira do criterio 1. Nao inclui o `criado_at`, que e historico.
    ("kamba_app", "bookings", "UPDATE"): {"estado", "hold_expires_at", "version"},
    # KAM-091: as **seis** colunas do `UPDATE_DA_APP` da revisao `0034`, e o que
    # fica de fora e a afirmacao. Nao inclui o `onboarding_id` nem o `step`, que
    # sao a chave primaria — mudar um deles era transformar o passo de um caso
    # no passo de outro, e o `abrir` reabre o par que ja existe em vez de o
    # mover. Nao inclui o `tenant_id`: ele e **pre-alocado** e nao tem FK para
    # `tenants`, pelo que nada no catalogo apanharia uma linha movida para outro
    # tenant — e com `WITH CHECK (tenant_id = app.tenant_id)` a `tenant_iso`
    # recusa escrever para fora, mas nao recusa reescrever a coluna com o
    # proprio valor de outro caso. Nao inclui o `criado_at`, que e historico.
    ("kamba_app", "provisioning_step", "UPDATE"): {
        "status",
        "attempt",
        "external_id",
        "error_code",
        "status_de_espera",
        "atualizado_at",
    },
    # KAM-053: as **quatro** colunas do `UPDATE_DO_INBOX` da revisao `0029`, e a
    # lista e exacta nos dois sentidos. As duas entradas sao iguais de proposito
    # — o `kamba_pay_hooks` marca o desfecho do que acabou de receber e o
    # `kamba_batch` marca o do que processou —, e o que importa e o que **nao**
    # esta nelas: o `body`, o `body_hash`, os `headers`, o `source_ip` e o
    # `recebido_at`. O que entrou pela rede nao se reescreve, e e isso que faz
    # do inbox uma prova em vez de um registo de trabalho.
    #
    # Um `GRANT UPDATE (body)` a mais era invisivel em qualquer matriz de
    # tabela — ali o inbox diz `{"SELECT", "INSERT"}` para o papel dos hooks —,
    # e com ele quem atende a rede reescrevia o corpo **depois** de o HMAC ter
    # sido verificado: a assinatura passava a valer sobre um corpo que ja nao e
    # o que chegou. E a razao medida no KAM-015 com outro nome de coluna, e aqui
    # a consequencia e pior do que reescrever uma chave de idempotencia.
    #
    # O `id` tambem nao esta: e `GENERATED ALWAYS AS IDENTITY` e e a ordem por
    # que o *worker* varre o que falta processar.
    ("kamba_pay_hooks", "payment_callbacks_inbox", "UPDATE"): {
        "estado", "processado_at", "erro", "authn_ok",
    },
    ("kamba_batch", "payment_callbacks_inbox", "UPDATE"): {
        "estado", "processado_at", "erro", "authn_ok",
    },
    # KAM-053: as **seis** colunas da `payment_accounts` que o papel dos
    # *webhooks* le. E tudo o que a `resolve_webhook_token` devolve, e e tudo o
    # que ele precisa para resolver `webhook_token -> conta` antes de existir
    # contexto de tenant (secao 5.1).
    #
    # **O `webhook_token` nao esta aqui, e e a correccao mais consequente desta
    # entrada.** Ele esteve, e a revisao adversarial mediu o que isso custava:
    # com `SELECT` na coluna do segredo e uma politica `USING (true)` — que e o
    # que o `SECURITY INVOKER` obriga a ter —, este papel fazia
    # `SELECT webhook_token FROM platform.payment_accounts` e **enumerava** o
    # segredo de callback de todas as PMEs. Medido: 36 linhas e 36 *tokens*, sem
    # contexto de tenant. Para os facilitadores sem assinatura (OPG, EMIS,
    # MoMenu) o *token* e a **unica** credencial do callback (secao 5).
    #
    # ## Como se compara uma coluna sem ter `SELECT` nela
    #
    # A politica `pay_hooks_token` passou a carregar o predicado:
    #
    #     USING (webhook_token = NULLIF(current_setting('app.webhook_token',
    #                                                   true), ''))
    #
    # A expressao de uma politica e definida pelo **dono** da tabela, e os
    # privilegios de coluna conferem-se contra as colunas que a **consulta**
    # referencia — nao contra as que a politica referencia. Logo o papel compara
    # o `webhook_token` sem o poder ler: sem *token*, zero linhas; com um
    # *token*, uma. Nao ha enumeracao porque nao ha consulta que devolva mais do
    # que a linha que quem pergunta ja identificou.
    #
    # **Tres versoes, e as duas primeiras falharam por razoes opostas:** uma
    # segunda `SECURITY DEFINER` nao funciona (corre como o dono, que e
    # `NOBYPASSRLS`, e o `FORCE` prende-o — zero linhas), e o `INVOKER` com
    # `USING (true)` funciona e abre a enumeracao. A terceira resolve as duas, e
    # deixa a lista aprovada de `ci/secdef_allowlist.yaml` com **uma** entrada,
    # que e o que o DoD do bloco pede.
    #
    # O que continua de fora pela mesma razao de sempre: o `credenciais_ref` (o
    # caminho no cofre para as credenciais do facilitador daquela PME), o
    # `manual_instrucoes` (o IBAN ou a carteira que o dono escreveu), o
    # `liquidacao_destino`, o `iec` e o `checklist`.
    #
    # Dito sem eufemismo, porque e o que esta lista existe para nao esconder:
    # com um *token* valido, este papel le seis colunas da conta **desse**
    # *token*, seja de que tenant for. E a leitura que o secao 5.1 exige —
    # resolver um *token* opaco sem saber de quem e — e o papel nao chega a mais
    # nada: nao le cobrancas, nao le o ledger, e nao executa a porta.
    ("kamba_pay_hooks", "payment_accounts", "SELECT"): {
        "id", "tenant_id", "provider", "entidade", "pos_id", "estado",
    },
}
PRIVILEGIOS_DE_COLUNA = ("SELECT", "INSERT", "UPDATE", "REFERENCES")

#: Em que esquema vive cada tabela da matriz. **Omissao `platform`**, porque era
#: onde viviam todas: o KAM-030 trouxe a primeira de outro esquema
#: (`dat.llm_call_log`), e sem isto a consulta da matriz procurava-a em
#: `platform`, nao encontrava coluna nenhuma e a bateria falhava com
#: «llm_call_log sem colunas» — o que e o comportamento certo de um inventario
#: que nao sabe onde a tabela esta, e nao um falso negativo.
ESQUEMA_DA_TABELA = {
    "llm_call_log": "dat",
    # KAM-047: as quatro da agenda (revisao `0025`).
    "services": "servicos",
    "resources": "servicos",
    "availability_rules": "servicos",
    "bookings": "servicos",
}


def esquema_de(tabela: str) -> str:
    return ESQUEMA_DA_TABELA.get(tabela, "platform")

#: As tabelas cuja matriz se confere **coluna a coluna**, nos dois sentidos: as
#: quatro da identidade (KAM-008) e as cinco de eventos (KAM-005). Sao as que
#: tem privilegios por coluna, ou onde um privilegio de coluna a mais seria
#: invisivel na matriz de tabela.
TABELAS_COM_MATRIZ_DE_COLUNA = (
    # KAM-070 (0038): as duas, e cada uma pela razao oposta da outra.
    #
    # A `dsar_requests` tem `UPDATE` **por coluna** para dois papeis — duas
    # colunas, em `COLUNAS_POR_PAPEL` — e entra pela razao do
    # `provisioning_step`: a matriz de tabela nao ve um privilegio de coluna, e
    # uma coluna a mais naquele `GRANT` era invisivel nela. O que uma coluna a
    # mais daria esta escrito na entrada: com o `prazo_interno_at` concedido, o
    # prazo do criterio 1 passa a poder ser empurrado por quem o devia cumprir.
    #
    # A `erasure_ledger` entra **sem ter privilegio de coluna nenhum**, pela
    # razao da `payment_events` e com a mesma forca: o que se prende e a
    # **ausencia**. Ninguem tem `UPDATE` nem `DELETE` nesta tabela, e e so isso
    # que a faz *append-only* — nao ha *trigger* `deny_mutation` por baixo. Um
    # `GRANT UPDATE (aplicado_at) ON erasure_ledger TO kamba_batch` nao aparece
    # no `has_table_privilege`, e com ele a linha que diz «o STO apagou em T»
    # passa a poder ser reescrita para outro instante: o registo de apagamentos
    # que o criterio 6 le depois de um restauro deixa de ser prova de nada, e
    # nenhuma matriz de tabela diz uma palavra.
    "dsar_requests",
    "erasure_ledger",
    # KAM-090 (0040): as duas **sem privilegio de coluna nenhum**, pela razao
    # da `erasure_ledger`: o que se prende e a **ausencia**. Um
    # `GRANT UPDATE (conteudo) ON contract_document` nao aparece no
    # `has_table_privilege` — o *trigger* recusava-o mesmo assim, mas o
    # `GRANT UPDATE (aceite_em) ON contract_acceptance` nao tem *trigger* por
    # baixo, e reescrevia a hora de uma prova.
    "contract_acceptance",
    "contract_document",
    # KAM-091 (0034): o estado da saga. Tem `UPDATE` **por coluna** para o
    # `kamba_app` — seis —, e entra aqui porque uma coluna a mais naquele
    # `GRANT` era **invisivel** na matriz de tabela: o
    # `has_table_privilege(..., 'UPDATE')` devolve `false` com ou sem
    # `GRANT UPDATE (coluna)`.
    #
    # E o que uma coluna a mais daria e exactamente o que a revisao recusa: um
    # `GRANT UPDATE (tenant_id)` deixava a aplicacao mover a linha de um caso
    # para o tenant de outro, e nada no catalogo o apanharia — esta tabela nao
    # tem FK para `tenants`, porque e o passo 1 da saga que escreve essa linha.
    "provisioning_step",
    # KAM-054 (0032): as quatro. Duas tem privilegio por coluna — o
    # `payment_confirmers` (`papel`, `pode_segunda_aprovacao`, `ativo`) e a
    # `refund_cases` (`estado`, `prova_ref`, `fechado_at`) —, e as outras duas
    # entram pela mesma razao das de eventos: um `GRANT UPDATE (coluna)` a mais
    # seria **invisivel** na matriz de tabela, e numa delas isso e a diferenca
    # entre um registo e um rascunho.
    "payment_confirmers",
    "manual_confirmations",
    "refund_cases",
    "fraud_signals",
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
    # KAM-021: pela mesma razao — a matriz de tabela nao ve um privilegio de
    # coluna a mais, nem a **ausencia** de um.
    "channel_quality_log",
    # KAM-022: as duas, pela mesma razao.
    "consent_event",
    "consent_texts",
    # KAM-016: pela mesma razao, e aqui o que se prende e a **ausencia** de
    # qualquer `UPDATE` — uma mutacao que acrescente um `GRANT UPDATE (fase)` a
    # `kamba_app` sobrevive sem esta linha, e com ela morre.
    "channel_onboarding",
    # KAM-017: pela mesma razao, e aqui o que se prende e a **presenca** da
    # lista exacta — uma mutacao que acrescente o `channel_id` ao `GRANT UPDATE`
    # sobrevive sem esta linha, e com ela morre.
    "channel_coexistence",
    # KAM-029: e **a mesma razao medida no KAM-015**, com outro nome de coluna.
    # Ali era «a aplicacao passa a poder reescrever a chave de idempotencia»;
    # aqui e o `args_hash`, e a consequencia e pior: a recusa
    # `INTENT_REUSED_WITH_DIFFERENT_CONTENT` do criterio 3 existe para apanhar
    # um `cart_id` reutilizado com outro conteudo, e um `GRANT UPDATE
    # (args_hash)` a mais deixava quem a ia accionar reescrever a prova e
    # passar. Nenhuma matriz de tabela ve isso.
    "tool_idempotency",
    # KAM-028, posta aqui pelo KAM-029 (divida **111**): a `tool_audit` tem
    # `INSERT` **por coluna** desde que nasceu e nunca entrou nesta lista, pelo
    # que uma coluna a mais naquele `GRANT` era invisivel em qualquer matriz.
    #
    # E o que uma coluna a mais daria e exactamente o que a propria revisao
    # `0021` escreve que ninguem pode: um `GRANT INSERT (ts)` punha o chamador a
    # escolher o instante da sua propria linha de auditoria («uma coluna que
    # nenhum chamador pode escrever e uma coluna que nenhum chamador tenta
    # escrever — e o `ts` de uma linha de auditoria nao e do chamador»), e um
    # `GRANT INSERT (id)` deixava-o escolher a ordem, que e o que torna a
    # cobertura do critero 5 daquele ticket ponderavel.
    #
    # Encontrada a declarar a `tool_idempotency` e a olhar para a vizinha.
    "tool_audit",
    # KAM-030, pela mesma razao e no mesmo dia: a `dat.llm_call_log` nasce com
    # `INSERT` por coluna, e entrar aqui de inicio e mais barato do que uma
    # divida a fechar tres linhas de versao depois.
    "llm_call_log",
    # KAM-014 e KAM-018, e esta entrou **medida**, como a `outbound_messages`.
    # A matriz de `conversations` esta escrita em `COLUNAS_POR_PAPEL` desde o
    # KAM-018, com as quatro colunas de `UPDATE` do `kamba_app` e um comentario
    # longo sobre as quatro que ficam de fora — e **nunca foi lida**, porque a
    # tabela nao estava nesta lista. Dados mortos: o
    # `test_privilegios_por_coluna_nas_tabelas_com_matriz` so itera esta tupla.
    #
    # O preco esta medido: a mutacao `modos 0016: a app perde o UPDATE do mode`
    # — tirar o `mode` das colunas que a `0016` concede — **sobreviveu** a noite
    # de 2026-10-26. A matriz de tabela nao a podia ver (ali `conversations` diz
    # `{"SELECT", "INSERT"}`, e o `has_table_privilege` devolve `false` para
    # `UPDATE` com ou sem o `GRANT` por coluna), e nenhum teste da suite `tests`
    # tentava um `UPDATE platform.conversations`. Com esta linha, a entrada
    # passa a ser afirmada nos **dois** sentidos, e cobre tambem o par de
    # `kamba_identity`, hoje igualmente morto.
    #
    # A propria `0016` aponta para um ficheiro que nao existe —
    # «Medido em `db/tests/test_modos_privilegios.py`» — e e essa a raiz.
    "conversations",
    # KAM-047: a `servicos.bookings` nasce com `UPDATE` **por coluna**, e entra
    # aqui de inicio pela razao que a `llm_call_log` escreveu — e mais uma, que e
    # desta tabela. O que uma coluna a mais daria: com `inicio_at` ou `fim_at` no
    # `GRANT`, a aplicacao movia uma marcacao de um intervalo para outro com um
    # `UPDATE`, e a restricao de exclusao do intervalo novo **nao** era
    # confrontada pela via que o codigo usa — a barreira do criterio 1 cai por um
    # `GRANT` de uma palavra, sem que matriz de tabela nenhuma o veja.
    #
    # As outras tres de `servicos` **nao** entram: nao tem privilegio de coluna
    # nenhum, e uma linha de matriz de coluna para uma tabela cujos `GRANT` sao
    # todos ao nivel da tabela repetia o que a matriz de tabela ja afirma.
    "bookings",
    # KAM-053: as **tres** tabelas que a revisao `0029` traz a esta lista, e
    # cada uma por uma razao diferente.
    #
    # O `payment_callbacks_inbox` tem `UPDATE` **por coluna** para dois papeis,
    # e o que uma coluna a mais daria esta escrito em `COLUNAS_POR_PAPEL`: com
    # o `body` no `GRANT`, quem atende a rede reescrevia o corpo depois de o
    # HMAC ter sido verificado. Nenhuma matriz de tabela ve isso.
    #
    # A `payment_accounts` **entra agora e nao na `0027`**, e e a divida 111
    # outra vez: ali os `GRANT` eram todos ao nivel da tabela e a linha nao
    # fazia falta; a `0029` da-lhe o primeiro `GRANT` por coluna — as sete do
    # `kamba_pay_hooks` —, e sem esta entrada um `GRANT SELECT
    # (credenciais_ref)` a mais era invisivel em qualquer matriz. E a coluna
    # que guarda o caminho das credenciais do facilitador, lida pelo papel que
    # atende a rede.
    #
    # A `payment_events` entra **sem ter privilegio de coluna nenhum**, pela
    # razao das de eventos e com a forca com que ela aqui vale mais: o que se
    # prende e a **ausencia**. Ninguem tem `INSERT` nesta tabela, e um
    # `GRANT INSERT (tenant_id, charge_id, ...)` por coluna a `kamba_app` nao
    # aparecia no `has_table_privilege` — abria uma segunda porta de escrita no
    # ledger sem que a matriz de tabela, o `deny_mutation` ou o
    # `secdef_allowlist` dissessem nada. E a porta que este ticket existe para
    # nao ter.
    #
    # A `payment_charges` entra pela **mesma** razao da `payment_events`, e a
    # primeira versao desta lista deixou-a de fora a escrever que a matriz de
    # tabela bastava. Nao basta, e e o defeito exacto que esta lista existe para
    # apanhar: um `GRANT UPDATE (estado) ON payment_charges TO kamba_app` nao
    # aparece no `has_table_privilege`, e com ele a aplicacao escrevia `paga`
    # sem passar pela `append_payment_event` — a barreira que o DoD do bloco
    # mede («nao existe caminho de codigo que escreva `paga` fora de
    # `append_payment_event`») cai por um `GRANT` de uma palavra, e nenhuma das
    # tres camadas da revisao a ve (o `deny_mutation` e da `payment_events`,
    # nao desta).
    #
    # A `payment_outbox_map` entra pela razao das de eventos: nenhum papel tem
    # `UPDATE` nela — encher a tabela e `INSERT` do lote, corrigir uma linha e
    # apagar e inserir — e um privilegio de coluna a mais era invisivel.
    "payment_callbacks_inbox",
    "payment_accounts",
    "payment_charges",
    "payment_events",
    "payment_outbox_map",
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
        # KAM-090: so o *trigger* do gate a escreve; com ela o tenant fingia
        # que ja tinha estado activo e saltava a exigencia das versoes vigentes.
        "primeira_activacao_at",
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

    def test_privilegios_de_tabela_no_servicos(self) -> None:
        """A matriz exacta das quatro da agenda (KAM-047), nos dois sentidos.

        Num teste proprio e nao dentro do `test_privilegios_de_tabela`: aquele
        itera `TABELAS` e qualifica com `platform.`, e as destas vivem noutro
        esquema. O `esquema_de` ja sabe onde; o que faltava era quem iterasse.

        Mede tambem o `USAGE` no esquema, que uma matriz de tabela nao ve: sem
        ele um `GRANT SELECT` nao serve de nada, e **com** ele a mais um papel
        ganha a lista de tabelas de um esquema que nao e dele.
        """
        cursor = self.ligar("admin").cursor()
        for tabela in TABELAS_SERVICOS_COM_MATRIZ:
            esquema = esquema_de(tabela)
            for papel, esperados in ESPERADO_POR_TABELA[tabela].items():
                for privilegio in PRIVILEGIOS_DE_TABELA:
                    with self.subTest(papel=papel, tabela=tabela, privilegio=privilegio):
                        cursor.execute(
                            "SELECT has_table_privilege(%s, %s, %s)",
                            (papel, f"{esquema}.{tabela}", privilegio),
                        )
                        self.assertEqual(cursor.fetchone()[0], privilegio in esperados)

        # Só os dois papéis que escrevem ou leem a agenda têm `USAGE`.
        for papel in (*sorted(ligacao.PAPEIS.values()), "public"):
            with self.subTest(papel=papel, privilegio="USAGE no esquema"):
                cursor.execute(
                    "SELECT has_schema_privilege(%s, 'servicos', 'USAGE')", (papel,)
                )
                esperado = papel in ("kamba_app", "kamba_batch", "kamba_migrator")
                self.assertEqual(cursor.fetchone()[0], esperado)
            with self.subTest(papel=papel, privilegio="CREATE no esquema"):
                cursor.execute(
                    "SELECT has_schema_privilege(%s, 'servicos', 'CREATE')", (papel,)
                )
                self.assertEqual(cursor.fetchone()[0], papel == "kamba_migrator")

    def test_so_a_app_executa_o_varrimento_dos_holds(self) -> None:
        """`servicos.expirar_holds` e do `kamba_app`, e de ninguem mais.

        **Nem do `kamba_batch`**, que seria o palpite natural para um
        varrimento. A razao e o outbox: a funcao emite `booking.cancelled` por
        `platform.evt_emitir`, e o `EXECUTE` dessa funcao e **so** do `kamba_app`
        desde a `0004` (ele e o produtor). Um varrimento como `kamba_batch`
        falhava no `evt_emitir` depois de ja ter alterado o estado — e ficavam
        holds libertados sem evento nenhum, que e exactamente o que o criterio 3
        pede que nao aconteca.

        **E nao do `PUBLIC`**, que e a omissao do PostgreSQL para cada funcao
        nova: deixa-la assim dava a um papel sem privilegio em `bookings` uma
        forma de a tentar alterar — recusada pela RLS, mas o caminho nao tem de
        existir.
        """
        linhas = self.consultar(
            "SELECT r.papel, has_function_privilege("
            "         r.papel, 'servicos.expirar_holds(integer)', 'EXECUTE') "
            "  FROM unnest(%s::text[]) AS r(papel) ORDER BY r.papel",
            (list((*sorted(ligacao.PAPEIS.values()), "public")),),
        )
        concedidos = {papel for papel, pode in linhas if pode}
        self.assertEqual(concedidos, {"kamba_app", "kamba_migrator"})

    def test_a_matriz_cobre_todos_os_papeis_do_bootstrap(self) -> None:
        """Um papel novo que ninguem ponha na matriz e um papel por medir."""
        # **O inventario da matriz passou a ter duas origens** (KAM-030): as do
        # `platform` e as do `dat`. A `dat.llm_call_log` tem `GRANT INSERT` por
        # coluna e por isso precisa de linha aqui — e a licao da divida 111, que
        # o `fix` do KAM-029 fechou para a `tool_audit` tres linhas de versao
        # antes. A particao nao entra: nao tem privilegio proprio nenhum.
        # **E passou a ter tres** (KAM-047): as do `platform`, a do `dat` e as
        # quatro do `servicos`. As quatro entram todas, ao contrario do `dat`
        # onde a particao fica de fora: as quatro tem privilegios concedidos
        # **por tabela**, e tres delas tem conjuntos diferentes (ver
        # `_agenda`). Uma tabela nova de `servicos` sem linha aqui falha este
        # teste, que e o proposito — «um papel novo que ninguem ponha na matriz
        # e um papel por medir», e vale igual para uma tabela nova.
        self.assertEqual(
            set(ESPERADO_POR_TABELA),
            set(TABELAS)
            | set(TABELAS_DAT_COM_MATRIZ)
            | set(TABELAS_SERVICOS_COM_MATRIZ),
        )
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
            esquema = esquema_de(tabela)
            cursor.execute(
                "SELECT r.papel, c.column_name::text, p.priv, "
                "       has_column_privilege(r.papel, %s, c.column_name, p.priv) "
                "  FROM unnest(%s::text[]) AS r(papel) "
                " CROSS JOIN unnest(%s::text[]) AS p(priv) "
                " CROSS JOIN information_schema.columns c "
                " WHERE c.table_schema = %s AND c.table_name = %s",
                (
                    f"{esquema}.{tabela}",
                    list(papeis),
                    list(PRIVILEGIOS_DE_COLUNA),
                    esquema,
                    tabela,
                ),
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
