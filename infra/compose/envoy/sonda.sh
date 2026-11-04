#!/usr/bin/env bash
# Sonda de saude do proxy de saida — KAM-076.
#
# Pergunta `/ready` a interface de administracao do Envoy, que escuta **so** em
# `127.0.0.1` dentro do contentor.
#
# PORQUE E UM FICHEIRO, E NAO UMA LINHA NO COMPOSE
#
# Duas razoes, e as duas foram medidas a 2026-11-03:
#
# 1. **A imagem do Envoy nao traz `curl` nem `wget`.** Traz `bash`, e e o
#    `/dev/tcp` dele que abre a ligacao. (Tambem traz `perl`; o `bash` chega.)
# 2. **Um `exec 3<>/dev/tcp/...` escrito no `healthcheck` do compose faz o gate
#    da cadeia de abastecimento falhar**, e com razao: o
#    `tools/supply_chain/runtime.py` exige que o executavel de um ponto de
#    arranque se encontre no repositorio (`arranque-nao-verificavel`), e
#    `3<>/dev/tcp/127.0.0.1/9901` parece-lhe um caminho que nao existe. A
#    correccao nao e afrouxar o gate — e por a sonda num ficheiro que se possa
#    ler, que e exactamente o que ele existe para obrigar.
#
# O `HTTP/1.1` com cabecalho `Host:` tambem foi medido: a interface de
# administracao responde `426 Upgrade Required` a um `HTTP/1.0`, e uma sonda em
# `HTTP/1.0` dava vermelho para sempre com o proxy saudavel.

set -euo pipefail

ANFITRIAO="${ENVOY_ADMIN_HOST:-127.0.0.1}"
PORTA="${ENVOY_ADMIN_PORT:-9901}"

exec 3<>"/dev/tcp/${ANFITRIAO}/${PORTA}"
printf 'GET /ready HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n' >&3

# Le so a linha de estado. O `/ready` devolve `LIVE` no corpo quando o servidor
# esta a servir; o que distingue saudavel de arrancar e o **codigo**.
LINHA="$(head -n 1 <&3)"
exec 3<&-

case "${LINHA}" in
  *" 200 "*) exit 0 ;;
  *) echo "proxy-saida: /ready devolveu: ${LINHA}" >&2; exit 1 ;;
esac
