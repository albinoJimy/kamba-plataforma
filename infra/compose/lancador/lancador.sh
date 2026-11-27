#!/bin/sh
# O lancador dos segredos de um contentor de `prod` (ADR-L002 §1, emenda do
# KAM-260, *proposta*). O deploy escreve, num `tmpfs` do anfitriao, um ficheiro
# por servico com os segredos dele; o compose monta-o so de leitura em
# `/run/kamba/segredos.env`. Aqui carrega-se esse ficheiro para o ambiente do
# processo e faz-se `exec` do comando: o processo le os segredos pela porta
# `SecretProvider`, como antes, e o `docker inspect` do contentor mostra o
# caminho da montagem e nunca um valor. Sem o ficheiro, o `.` falha e o
# contentor nao arranca: fecha, e nao abre.
#
# Gera-o `python -m compose_prod segredos`; mede-o `compose_prod inspeccao`.
set -eu
set -a
. /run/kamba/segredos.env
set +a
exec "$@"
