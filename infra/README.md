# Infraestrutura

| Caminho | O que é | Ticket |
|---|---|---|
| `compose/docker-compose.dev.yml` | Pilha de **desenvolvimento local**: Postgres 18.6 + pgvector, fila compatível com Redis (AOF), e os cinco serviços | KAM-001 |
| `compose/postgres/initdb/` | Bases e extensões do arranque local (sem tabelas) | KAM-001 |

## O que ainda não está aqui

O KAM-001 entrega **só** o ambiente local. Faltam, por desenho:

| O que falta | Ticket |
|---|---|
| Ambientes `dev`/`staging`/`prod` e infraestrutura como código (`infra/{modules,envs/*}`) | KAM-075 |
| Proxy inverso com TLS, proxy de saída com *allowlist* de FQDN, redes `edge` e `ops` | KAM-075, KAM-076 |
| Prometheus, Alertmanager, Grafana, Loki, sonda sintética externa | KAM-076 |
| `pgBackRest`, RPO/RTO, teste de restauro | KAM-077 |
| SBOM por imagem, assinatura cosign e `release.lock` (as imagens já vêm por *digest*, e cada serviço declara as suas saídas em `infra/egress/` e `services/*/egress.yaml`: KAM-067, `docs/supply-chain.md`) | KAM-078 |
| Pipeline de CI e gates *fail-closed* | KAM-002 |

A topologia-alvo está em `docs/tecnica/09` §3; as regras de rede em §3.2. Duas delas
já são cumpridas pelo compose local: a rede `data` é `internal: true` (sem rota
de saída) e nenhuma porta é publicada fora de `127.0.0.1`.
