"""A configuracao do proxy de saida, **gerada** da allowlist (KAM-076, criterio 3).

O ficheiro `infra/compose/envoy/egress.yaml` e gerado de
`infra/egress/proxy-saida.yaml` e versionado, como o `llm/litellm.config.yaml` e
gerado de `llm/aliases.yaml` (KAM-030) e o `canon/dicionario.yaml` de
`specs/02`. O gate corre `gerar --verificar`, que falha se o gerado estiver
desactualizado: a allowlist deixa de poder divergir da configuracao que a aplica.

## Porque gerar e nao escrever a mao

Sao duas listas de FQDN que tem de ser a mesma. Escritas a mao, divergem — e a
divergencia que importa e a silenciosa: acrescentar um destino ao `egress.yaml`
e esquecer o Envoy da um contrato que diz «sai» e uma rede que recusa, e o
contrario da um destino aberto que nenhum contrato declara. O `lint` ja compara
a allowlist com o que os servicos declaram; isto fecha o terceiro lado.

## Como o Envoy recusa, e como registar

A politica esta em dois `virtual_hosts`, e a ordem nao importa porque o Envoy
escolhe o mais especifico: o primeiro nomeia os dominios permitidos e encaminha
para o *cluster* de saida; o segundo e `domains: ["*"]` e responde **403** a
tudo o mais.

O registo — a metade do criterio 3 que se esquece — e um `access_log` em JSON
com a autoridade pedida, o metodo e o codigo de resposta. Um 403 nesse log **e**
a ligacao bloqueada e registada. Nao se registar corpo nem cabecalhos: um proxy
que registe o corpo dos webhooks guarda conversas (`docs/tecnica/08` §7.3).

O `:authority` de um CONNECT traz a porta (`graph.facebook.com:443`), e o de um
GET em claro nao. Por isso cada FQDN entra **duas vezes** na lista de dominios,
com e sem porta: so com uma delas, metade dos pedidos caia no `*` e era recusada
por engano — e um gate que recusa o que devia passar e desligado por quem o
encontra.
"""

from __future__ import annotations

from pathlib import Path

from kamba_yaml import YamlSubsetError, load_file

from .lint import ALLOWLIST, ENVOY, ConfiguracaoInvalida

#: A porta onde o proxy escuta, e a que os servicos de `app` tem em `HTTPS_PROXY`.
PORTA = 3128
#: A porta da interface de administracao, **so** em `127.0.0.1`: e dela que o
#: `healthcheck` do compose le `/ready`.
PORTA_ADMIN = 9901

_CABECALHO = """\
# Proxy de saida de producao — KAM-076, criterio 3.
#
# ********** FICHEIRO GERADO. NAO EDITAR A MAO. **********
#
# Gerado de `infra/egress/proxy-saida.yaml` por `python -m compose_prod gerar`.
# O gate 2 corre `gerar --verificar` e falha se este ficheiro divergir da
# allowlist — a razao esta em `tools/compose_prod/envoy.py`.
#
# Para acrescentar um destino: escreva-o em `infra/egress/<servico>.yaml` (o
# servico que o vai alcancar) **e** em `infra/egress/proxy-saida.yaml`, e corra
# o gerador. O `lint` recusa um destino na allowlist que nenhum servico declare.
"""


def _destinos(raiz: Path) -> list[tuple[str, int]]:
    caminho = raiz / ALLOWLIST
    if not caminho.is_file():
        raise ConfiguracaoInvalida(f"allowlist ausente: {ALLOWLIST}")
    try:
        dados = load_file(caminho)
    except YamlSubsetError as excepcao:
        raise ConfiguracaoInvalida(f"{ALLOWLIST}: ilegivel: {excepcao}") from excepcao
    if dados.get("por_omissao") != "negar":
        raise ConfiguracaoInvalida(f"{ALLOWLIST}: `por_omissao` nao e `negar`")
    destinos: list[tuple[str, int]] = []
    for item in dados.get("destinos") or []:
        fqdn = item.get("fqdn")
        if not fqdn:
            continue
        try:
            porta = int(item.get("porta"))
        except (TypeError, ValueError) as excepcao:
            raise ConfiguracaoInvalida(
                f"{ALLOWLIST}: destino `{fqdn}` sem `porta` legivel"
            ) from excepcao
        destinos.append((fqdn, porta))
    if not destinos:
        raise ConfiguracaoInvalida(
            f"{ALLOWLIST}: nenhum destino. Um proxy sem allowlist recusa tudo, e um "
            "ficheiro gerado vazio passaria o gate sem o dizer."
        )
    return sorted(set(destinos))


def compor(raiz: Path) -> str:
    """O texto da configuracao do Envoy, a partir da allowlist."""
    destinos = _destinos(raiz)
    dominios: list[str] = []
    for fqdn, porta in destinos:
        # Com e sem porta: ver a nota do cabecalho deste modulo.
        dominios.append(fqdn)
        dominios.append(f"{fqdn}:{porta}")

    linhas = [_CABECALHO, ""]
    linhas.append("admin:")
    linhas.append("  address:")
    linhas.append("    socket_address:")
    # So em `127.0.0.1`: a interface de administracao do Envoy reescreve
    # *clusters* em execucao, e `app` nao e sitio para isso.
    linhas.append("      address: 127.0.0.1")
    linhas.append(f"      port_value: {PORTA_ADMIN}")
    linhas.append("")
    linhas.append("static_resources:")
    linhas.append("  listeners:")
    linhas.append("    - name: saida")
    linhas.append("      address:")
    linhas.append("        socket_address:")
    linhas.append("          address: 0.0.0.0")
    linhas.append(f"          port_value: {PORTA}")
    linhas.append("      filter_chains:")
    linhas.append("        - filters:")
    linhas.append("            - name: envoy.filters.network.http_connection_manager")
    linhas.append("              typed_config:")
    linhas.append(
        '                "@type": type.googleapis.com/envoy.extensions.filters.network'
        ".http_connection_manager.v3.HttpConnectionManager"
    )
    linhas.append("                stat_prefix: saida")
    # Sem isto o Envoy responde 405 a um CONNECT, e CONNECT e como todo o
    # HTTPS atravessa um proxy explicito.
    linhas.append("                upgrade_configs:")
    linhas.append("                  - upgrade_type: CONNECT")
    linhas.append("                access_log:")
    linhas.append("                  - name: envoy.access_loggers.stdout")
    linhas.append("                    typed_config:")
    linhas.append(
        '                      "@type": type.googleapis.com/envoy.extensions'
        ".access_loggers.stream.v3.StdoutAccessLog"
    )
    linhas.append("                      log_format:")
    linhas.append("                        json_format:")
    # O registo do criterio 3. Autoridade, metodo e veredicto; nunca corpo.
    linhas.append('                          hora: "%START_TIME%"')
    linhas.append('                          metodo: "%REQ(:METHOD)%"')
    linhas.append('                          autoridade: "%REQ(:AUTHORITY)%"')
    linhas.append('                          veredicto: "%RESPONSE_CODE%"')
    linhas.append('                          motivo: "%RESPONSE_CODE_DETAILS%"')
    linhas.append('                          bytes_para_fora: "%BYTES_SENT%"')
    linhas.append('                          duracao_ms: "%DURATION%"')
    linhas.append("                route_config:")
    linhas.append("                  name: saida")
    linhas.append("                  virtual_hosts:")
    linhas.append("                    - name: permitidos")
    linhas.append("                      domains:")
    for dominio in dominios:
        linhas.append(f'                        - "{dominio}"')
    linhas.append("                      routes:")
    linhas.append("                        - match:")
    linhas.append("                            connect_matcher: {}")
    linhas.append("                          route:")
    linhas.append("                            cluster: saida-dinamica")
    linhas.append("                            upgrade_configs:")
    linhas.append("                              - upgrade_type: CONNECT")
    linhas.append("                                connect_config: {}")
    linhas.append("                    - name: negados")
    linhas.append("                      domains:")
    linhas.append('                        - "*"')
    linhas.append("                      routes:")
    linhas.append("                        - match:")
    linhas.append("                            connect_matcher: {}")
    linhas.append("                          direct_response:")
    linhas.append("                            status: 403")
    linhas.append("                            body:")
    linhas.append(
        '                              inline_string: "destino fora da allowlist do '
        'proxy de saida (KAM-076): declare-o em infra/egress/ e corra compose_prod gerar"'
    )
    linhas.append("                        - match:")
    linhas.append('                            prefix: "/"')
    linhas.append("                          direct_response:")
    linhas.append("                            status: 403")
    linhas.append("                            body:")
    linhas.append(
        '                              inline_string: "destino fora da allowlist do '
        'proxy de saida (KAM-076)"'
    )
    linhas.append("                http_filters:")
    linhas.append("                  - name: envoy.filters.http.dynamic_forward_proxy")
    linhas.append("                    typed_config:")
    linhas.append(
        '                      "@type": type.googleapis.com/envoy.extensions.filters'
        ".http.dynamic_forward_proxy.v3.FilterConfig"
    )
    linhas.append("                      dns_cache_config:")
    linhas.append("                        name: saida")
    linhas.append("                        dns_lookup_family: V4_ONLY")
    # `preresolve_hostnames` resolve a allowlist **no arranque**. Sem isto o
    # primeiro pedido a cada FQDN apanha a cache fria e pode voltar `503
    # dns_resolution_failure{resolve_timeout}` — medido pela revisao
    # adversarial, que viu o `graph.facebook.com` a dar 503 tres vezes e o
    # `api.anthropic.com` a falhar a frio e a passar na segunda tentativa.
    # Um 503 no primeiro webhook da Meta e uma mensagem perdida.
    linhas.append("                        dns_refresh_rate: 60s")
    linhas.append("                        dns_query_timeout: 5s")
    linhas.append("                        preresolve_hostnames:")
    for fqdn, porta in destinos:
        linhas.append(f"                          - address: {fqdn}")
        linhas.append(f"                            port_value: {porta}")
    linhas.append("                  - name: envoy.filters.http.router")
    linhas.append("                    typed_config:")
    linhas.append(
        '                      "@type": type.googleapis.com/envoy.extensions.filters'
        ".http.router.v3.Router"
    )
    linhas.append("  clusters:")
    linhas.append("    - name: saida-dinamica")
    linhas.append("      lb_policy: CLUSTER_PROVIDED")
    linhas.append("      cluster_type:")
    linhas.append("        name: envoy.clusters.dynamic_forward_proxy")
    linhas.append("        typed_config:")
    linhas.append(
        '          "@type": type.googleapis.com/envoy.extensions.clusters'
        ".dynamic_forward_proxy.v3.ClusterConfig"
    )
    # O `dns_cache_config` vive **dentro** do `typed_config`, e nao ao lado:
    # medido a 2026-11-03, com ele ao lado o Envoy recusa o arranque com
    # «no such field: 'dns_cache_config'» em `CustomClusterType`. O nome do
    # cache tem de ser o mesmo do filtro, senao sao duas caches e o *cluster*
    # nao encontra o endereco que o filtro resolveu.
    linhas.append("          dns_cache_config:")
    linhas.append("            name: saida")
    linhas.append("            dns_lookup_family: V4_ONLY")
    # As mesmas tres chaves do filtro: o nome da cache e partilhado, e o Envoy
    # exige que a configuracao bata **dos dois lados** — se divergir, sao duas
    # caches e o *cluster* nao encontra o endereco que o filtro resolveu.
    linhas.append("            dns_refresh_rate: 60s")
    linhas.append("            dns_query_timeout: 5s")
    linhas.append("            preresolve_hostnames:")
    for fqdn, porta in destinos:
        linhas.append(f"              - address: {fqdn}")
        linhas.append(f"                port_value: {porta}")
    linhas.append("")
    return "\n".join(linhas)


def gerar(raiz: Path, escrever: bool = True) -> tuple[bool, str]:
    """Escreve (ou compara) a configuracao. Devolve (mudou, caminho relativo)."""
    novo = compor(raiz)
    caminho = raiz / ENVOY
    antigo = caminho.read_text(encoding="utf-8") if caminho.is_file() else None
    mudou = antigo != novo
    if escrever and mudou:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(novo, encoding="utf-8", newline="\n")
    return mudou, ENVOY
