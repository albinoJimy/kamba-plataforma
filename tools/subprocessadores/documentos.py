"""Os dois documentos gerados do inventario (KAM-069, criterios 5 e 9).

    docs/publico/subprocessadores.md     a lista publica (requisito 4 de `E3`)
    docs/seguranca/mapa_tratamentos.md   o mapa de tratamentos (requisito 9)

**Gerados e versionados**, como o `canon/dicionario.yaml`: entram no
repositorio, e o `check` recusa se o que esta no disco nao e o que o inventario
produz. Duas fontes a mao punham a lista publica a nomear um subprocessador que
o inventario nao tem — e a lista publica e um compromisso com titulares de
dados, nao uma pagina de marketing.

## Porque e que a lista publica e **separada** do mapa

Sao audiencias diferentes e o conteudo nao e o mesmo. O requisito 4 de `E3` pede
uma «pagina publica de subprocessadores» — quem trata dados em nome da PME, para
que o titular o saiba. O requisito 9 pede um «mapa de tratamentos» para a APD,
com categorias, finalidades, destinatarios, transferencias, prazos e seguranca.

A lista publica **nao leva o credor, nem a referencia de contrato, nem o estado
do procedimento**: sao informacao interna de conformidade, e publica-las dizia
ao mundo qual dos nossos contratos esta por assinar. O que ela leva e o que o
titular precisa de saber: quem, para que, que dados e para onde.

## A versao esta nos dois, e e a mesma

O criterio 9 pede «alterar uma linha altera a versao». A versao vive no
`Inventario.versao_do_mapa`, derivada por `sha256` das linhas que decidem, e
aparece nos dois documentos — se a lista publica tivesse versao propria, havia
duas respostas a «esta actualizado?».
"""

from __future__ import annotations

from .inventario import Inventario, Subprocessador

#: Onde cada documento vive, relativo a raiz.
CAMINHO_PUBLICO = "docs/publico/subprocessadores.md"
CAMINHO_MAPA = "docs/seguranca/mapa_tratamentos.md"

#: O aviso que os dois levam. **Nao e formalidade:** o `Mapa_Tratamentos_v1.md`
#: do KAM-105 leva-o, o `GoLive_Gate.md` leva-o, e a razao e a mesma — nada
#: nestes documentos e aconselhamento juridico, e os estados CONFIRMADO,
#: INDICIO e NAO VERIFICADO tem o sentido da evidencia de pesquisa da KAMBÁ.
AVISO = (
    "> **Este documento é gerado e não é aconselhamento jurídico.** Sai de\n"
    "> [`gov/subprocessadores.yaml`](../../gov/subprocessadores.yaml) por\n"
    "> `python -m subprocessadores`, e editá-lo à mão é uma alteração que o\n"
    "> *gate* desfaz. Tudo o que toca à Lei 22/11, à APD e aos Termos da Meta\n"
    "> leva *(a confirmar por parecer)*, e os estados **CONFIRMADO**,\n"
    "> **INDÍCIO** e **NÃO VERIFICADO** têm o sentido da evidência de pesquisa\n"
    "> da KAMBÁ — e **não são promovidos** aqui."
)


def _sim_nao(valor: bool) -> str:
    return "sim" if valor else "**não**"


def _ou_falta(valor: str | None) -> str:
    return f"`{valor}`" if valor else "**não há**"


def _linha_publica(s: Subprocessador) -> str:
    return (
        f"| {s.designacao} | {s.funcao} | {s.dados_pessoais} | "
        f"{s.pais_hipotese} | {s.estado} |"
    )


def lista_publica(inventario: Inventario, versao: str) -> str:
    """A lista publica de subprocessadores (requisito 4 de `E3`)."""
    autorizados = len(inventario.subprocessadores) - len(inventario.pendentes)
    linhas = [
        "# Subprocessadores — KAMBÁ",
        "",
        "| Campo | Valor |",
        "|---|---|",
        "| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de "
        "comércio conversacional para Angola |",
        "| Documento | Lista pública de subprocessadores (requisito 4 de "
        "`E3`) |",
        f"| Versão | {versao} |",
        "| Classificação | **Público** |",
        "| Ticket | KAM-069 (EPIC-07) |",
        "| Documento-fonte | "
        "[`gov/subprocessadores.yaml`](../../gov/subprocessadores.yaml); "
        "`../tecnica/08_Seguranca_Conformidade.md` §8.3.2 |",
        "",
        AVISO,
        "",
        "---",
        "",
        "## 1. Quem trata dados em nome da sua loja",
        "",
        "Cada PME que usa a KAMBÁ é a responsável pelos dados dos seus "
        "clientes, e a KAMBÁ é subcontratada (`../tecnica/08` §8.2; o papel "
        "definitivo é a decisão **D9**, ainda aberta). Para prestar o serviço, "
        "a KAMBÁ recorre aos subprocessadores abaixo.",
        "",
        f"**{len(inventario.subprocessadores)} subprocessadores. "
        f"{autorizados} com procedimento concluído junto da APD.**",
        "",
        "| Subprocessador | Função | Dados pessoais tratados | Destino "
        "(hipótese) | Estado do procedimento |",
        "|---|---|---|---|---|",
    ]
    linhas += [_linha_publica(s) for s in inventario.subprocessadores]
    linhas += [
        "",
        "## 2. O que «estado do procedimento» quer dizer",
        "",
        "| Estado | Significado |",
        "|---|---|",
        "| `pendente` | O procedimento junto da APD não está concluído. "
        "**Nenhum dado pessoal de produção sai para este destino** (ADR-008): "
        "o *gate* de transferência nega por omissão, e o que corre são dados "
        "sintéticos |",
        "| `autorizado` | A APD respondeu e permite, e há contrato, retenção "
        "zero e não-treino arquivados |",
        "| `revogado` | Esteve autorizado e deixou de estar |",
        "| `negado` | A APD respondeu e não permite |",
        "",
        "**O destino é uma hipótese e não uma afirmação.** Os países "
        "confirmam-se contratualmente, e a lista de países «adequados» para "
        "efeito dos Arts. 33.º e 34.º da Lei 22/11 não foi encontrada "
        "publicamente (**NÃO VERIFICADO**). A KAMBÁ não infere adequação a "
        "partir do país: o que liberta uma transferência é a autorização ou a "
        "notificação à APD, por destino.",
        "",
        "## 3. Direitos do titular",
        "",
        "Pedidos de acesso, correcção, eliminação e oposição fazem-se pelo "
        "mesmo canal por onde a conversa começou (`../tecnica/08` §8.4). O "
        "prazo interno é de 30 dias.",
        "",
    ]
    return "\n".join(linhas)


def _linha_do_mapa(s: Subprocessador) -> str:
    return (
        f"| {s.nome} | {s.designacao} | {s.funcao} | {s.dados_pessoais} | "
        f"{', '.join(f'`{f}`' for f in s.finalidades)} | {s.pais_hipotese} | "
        f"{_sim_nao(s.pais_verificado)} | `{s.estado}` | "
        f"{_ou_falta(s.contrato_ref)} | {_sim_nao(s.retencao_zero)} | "
        f"{_sim_nao(s.sem_treino)} | {_ou_falta(s.apd_ref)} | {s.credor} |"
    )


def mapa_de_tratamentos(
    inventario: Inventario, versao: str, destinos: tuple[dict, ...] = ()
) -> str:
    """O mapa de tratamentos (requisito 9 de `E3`, `../tecnica/08` §8.6).

    **Com `destinos` vazio, o documento di-lo por extenso** em vez de parecer
    completo: o §8.6 manda gerar o mapa «a partir do inventario (§7.1) e do
    `tenant_destinations`, para nao divergir do sistema real», e um mapa que
    omitisse metade da fonte sem o dizer divergia em silencio — que e
    exactamente o defeito que a frase do §8.6 existe para impedir.
    """
    pendentes = inventario.pendentes
    linhas = [
        "# Mapa de tratamentos — KAMBÁ (gerado)",
        "",
        "| Campo | Valor |",
        "|---|---|",
        "| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de "
        "comércio conversacional para Angola |",
        "| Documento | Mapa de tratamentos por destino, **gerado** do "
        "inventário e de `platform.tenant_destinations` |",
        f"| Versão | {versao} |",
        "| Classificação | Documento de Referência — Interno; base da "
        "submissão à APD |",
        "| Ticket | KAM-069 (EPIC-07) |",
        "| Documento-fonte | "
        "[`gov/subprocessadores.yaml`](../../gov/subprocessadores.yaml); "
        "`platform.tenant_destinations` (revisão "
        "[`0036`](../../db/migrations/versions/0036_destinos_de_transferencia.py)); "
        "`../tecnica/08_Seguranca_Conformidade.md` §7.1, §8.3, §8.6 |",
        "| Relacionados | "
        "[`Mapa_Tratamentos_v1.md`](../tecnica/evidencia/validacao/Mapa_Tratamentos_v1.md) "
        "(o de KAM-105, escrito à mão antes de esta tabela existir); "
        "[`GoLive_Gate.md`](../tecnica/evidencia/validacao/GoLive_Gate.md) |",
        "",
        AVISO,
        "",
        "---",
        "",
        "## 1. A versão, e porque é que ela é um `sha256`",
        "",
        f"`{versao}` — a versão declarada do inventário, mais os doze primeiros "
        "dígitos do `sha256` das linhas que decidem (sem as `nota`, pela razão "
        "que o `ci/llm-aliases.lock` do KAM-030 já escreve: o que se *hasheia* "
        "é o conteúdo que decide, não o texto que o descreve).",
        "",
        "O critério 9 do KAM-069 pede que **alterar uma linha altere a "
        "versão**, e um número escrito à mão não tem essa propriedade: "
        "esquece-se. Mudar um país, um estado, uma finalidade ou a *checklist* "
        "de qualquer linha muda estes doze dígitos; reescrever uma nota não.",
        "",
        "## 2. O que esta versão leu",
        "",
        "| Fonte | O que dá | Lido |",
        "|---|---|---|",
        f"| [`gov/subprocessadores.yaml`](../../gov/subprocessadores.yaml) | "
        f"os subprocessadores, a função, os dados e a *checklist* | "
        f"**{len(inventario.subprocessadores)}** linhas |",
        f"| `platform.tenant_destinations` (revisão `0036`) | a configuração "
        f"por tenant e destino, com o `apd_ref` e a janela de validade | "
        f"**{len(destinos)}** linhas |",
        "",
    ]
    if not destinos:
        linhas += [
            "> **Zero linhas de `platform.tenant_destinations`, e isto diz-se "
            "em vez de se omitir.** A tabela existe desde a revisão `0036` e "
            "**não tem linha nenhuma**: configurar um destino exige um "
            "`apd_ref`, e o `ext:KAM-105` fechou com **0 de 14** destinos com "
            "`apd_ref` (`../tecnica/evidencia/validacao/Seguimento_APD.md` §1 "
            "— zero submetidos, zero com número de protocolo).",
            ">",
            "> Logo este mapa descreve **o que a plataforma trataria**, pelo "
            "inventário, e não **o que ela trata**, que hoje é nada em "
            "produção. A segunda metade enche-se quando houver uma "
            "autorização; até lá, a ausência é o facto, e o `../tecnica/08` "
            "§8.6 pede que o mapa não divirja do sistema real — não que "
            "pareça completo.",
            "",
        ]
    linhas += [
        "## 3. Os tratamentos, por destino",
        "",
        "| Destino | Designação | Função | Dados pessoais | Finalidades | "
        "País (hipótese) | País verificado | Estado | Contrato | Retenção "
        "zero | Não-treino | `apd_ref` | Credor |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    linhas += [_linha_do_mapa(s) for s in inventario.subprocessadores]
    linhas += [
        "",
        f"**{len(pendentes)} de {len(inventario.subprocessadores)} destinos "
        "estão `pendente`.** Enquanto um destino não estiver `autorizado` com "
        "`apd_ref`, o *gate* de transferência "
        "(`libs/py-core/src/kamba_core/destinos/`) nega-o: nenhum dado pessoal "
        "de produção sai para lá (ADR-008).",
        "",
        "## 4. O que este mapa não decide, e a quem fica",
        "",
        "| Item | Estado | Credor |",
        "|---|---|---|",
        "| Qual é cada subprocessador | **nenhum está escolhido** — escolher "
        "um num ficheiro de código é o que o ADR-008 existe para impedir | o "
        "fundador, com o parecer de KAM-104 |",
        "| Lista de países «adequados» (Arts. 33.º–34.º) | **NÃO VERIFICADO**: "
        "não encontrada publicamente; a UE e a África do Sul são hipóteses e os "
        "EUA provavelmente exigem autorização (INDÍCIO) | KAM-104 |",
        "| Papel da KAMBÁ: responsável ou subcontratada | **D9**, aberta; a "
        "omissão é `subcontratada` (`../tecnica/08` §8.2, «até parecer») | "
        "KAM-104 |",
        "| Local do alojamento e das cópias | **D1**, aberta; depende de ≥ 3 "
        "cotações, nenhuma pedida | o fundador |",
        "| O CDN que termina TLS é subprocessador | **D12**, aberta; há um "
        "caminho que a dispensa (não pôr os webhooks atrás do proxy) | o "
        "fundador |",
        "| Contrato de subcontratação (DPA) com cada PME | **não está "
        "redigido** | KAM-090 |",
        "| Submissão, taxas e número de protocolo | **nenhuma submissão "
        "feita** | KAM-105 |",
        "| Observabilidade como destino | o `purpose` existe no domínio e "
        "**nenhum subprocessador o declara**: o §8.3.2 não tem linha de "
        "observabilidade | KAM-080 e KAM-105 |",
        "| Reconciliar as 11 linhas do §8.3.2 com os 14 destinos da folha de "
        "seguimento | o §8.3.2 junta alojamento e cópias numa linha, e não tem "
        "a sonda sintética nem o melhoramento de imagem | KAM-105 |",
        "| Registo das mudanças deste mapa no `audit_log` | **por ligar**: não "
        "há processo de plataforma que o gere em execução | KAM-071 |",
        "",
    ]
    return "\n".join(linhas)
