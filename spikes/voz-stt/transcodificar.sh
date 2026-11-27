#!/bin/sh
# Transcodificacao do corpus do spike de voz para Opus/OGG (KAM-107).
#
#   transcodificar.sh opus    ENTRADA SAIDA.ogg
#   transcodificar.sh juntar  SAIDA.ogg ALVO_S ENTRADA1 [ENTRADA2 ...]
#   transcodificar.sh duracao FICHEIRO
#
# `opus` converte uma gravacao (WAV, M4A, o que o gravador der) para o formato
# das notas de voz do WhatsApp: Opus num contentor OGG, mono. `juntar` monta um
# clip de latencia de 5, 15 ou 30 s: concatena as entradas, pela ordem, e corta
# no alvo; recusa se a soma nao chegar ao alvo. `duracao` imprime a duracao em
# segundos, que e o que vai para a coluna `duracao_s` do manifesto.
#
# Os parametros do WhatsApp -- 16 kHz, mono, cerca de 24 kbit/s, perfil VoIP --
# sao NAO VERIFICADO: sao o que se costuma ler de uma nota de voz, nao o que uma
# fonte da Meta diz. Confirmam-se com `ffprobe` sobre uma nota de voz que um
# membro da equipa grave e envie a si proprio, so os metadados, e acertam-se
# aqui por variavel de ambiente, sem mexer no script:
#
#   KAMBA_VOZ_TAXA=16000  KAMBA_VOZ_BITRATE=24k
#
# O `-map_metadata -1` tira os metadados da gravacao (modelo do aparelho, data,
# por vezes localizacao). Nao ha normalizacao de volume de proposito: o WhatsApp
# nao a faz, e o spike mede o que o STT vai receber.
#
# A saida tem de ficar FORA de qualquer repositorio git: o script recusa
# escrever numa pasta com um `.git` acima (codigo 3), porque o audio e a voz de
# pessoas e este repositorio e publico.
#
# Correr sem ffmpeg no anfitriao (o que esta maquina nao tem), com o audio numa
# pasta fora do repositorio montada em /a e o script so de leitura em /s:
#
#   MSYS_NO_PATHCONV=1 docker run --rm -v "/c/fora/audio:/a" \
#     -v "$PWD/spikes/voz-stt:/s:ro" -w /a --entrypoint sh \
#     jrottenberg/ffmpeg:7.1-alpine /s/transcodificar.sh opus in.wav F01/C0001.ogg
set -eu

FFMPEG=${FFMPEG:-ffmpeg}
FFPROBE=${FFPROBE:-ffprobe}
TAXA=${KAMBA_VOZ_TAXA:-16000}
BITRATE=${KAMBA_VOZ_BITRATE:-24k}

uso() {
  echo "uso: $0 opus ENTRADA SAIDA.ogg | juntar SAIDA.ogg ALVO_S ENTRADA... | duracao FICHEIRO" >&2
  exit 2
}

fora_do_repositorio() {
  # Sobe ate a primeira pasta que ja existe, verifica dali para cima, e so
  # depois cria a pasta da saida: recusar nao deixa pastas vazias para tras.
  d=$(dirname -- "$1")
  while [ ! -d "$d" ]; do d=$(dirname -- "$d"); done
  d=$(cd -- "$d" && pwd)
  while :; do
    if [ -e "$d/.git" ]; then
      echo "recusado: $1 fica dentro de um repositorio git ($d)" >&2
      exit 3
    fi
    [ "$d" = "/" ] && break
    d=$(dirname -- "$d")
  done
  mkdir -p -- "$(dirname -- "$1")"
}

duracao() {
  "$FFPROBE" -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$1"
}

opus() {
  fora_do_repositorio "$2"
  "$FFMPEG" -nostdin -hide_banner -loglevel error -y -i "$1" \
    -map_metadata -1 -vn -ac 1 -ar "$TAXA" \
    -c:a libopus -b:a "$BITRATE" -application voip -f ogg "$2"
}

juntar() {
  saida=$1
  alvo=$2
  shift 2
  fora_do_repositorio "$saida"
  [ "$#" -ge 1 ] || uso
  case $alvo in
    5|15|30) ;;
    *) echo "alvo tem de ser 5, 15 ou 30 s, nao $alvo" >&2; exit 2 ;;
  esac
  total=0
  for f in "$@"; do
    d=$(duracao "$f")
    total=$(awk -v a="$total" -v b="$d" 'BEGIN { printf "%.3f", a + b }')
  done
  if awk -v t="$total" -v a="$alvo" 'BEGIN { exit !(t < a) }'; then
    echo "as entradas somam ${total} s, menos do que o alvo de ${alvo} s" >&2
    exit 1
  fi
  n=$#
  filtro=""
  i=0
  # Reescreve "$@" de `a b` para `-i a -i b` sem `eval`: o `for` expande a lista
  # uma vez, a entrada, e cada volta acrescenta o par e tira a cabeca.
  for f in "$@"; do
    filtro="${filtro}[${i}:a]"
    i=$((i + 1))
    set -- "$@" -i "$f"
    shift
  done
  "$FFMPEG" -nostdin -hide_banner -loglevel error -y "$@" \
    -filter_complex "${filtro}concat=n=${n}:v=0:a=1[a]" -map "[a]" -t "$alvo" \
    -map_metadata -1 -ac 1 -ar "$TAXA" -c:a libopus -b:a "$BITRATE" -application voip -f ogg "$saida"
}

[ "$#" -ge 1 ] || uso
comando=$1
shift
case $comando in
  opus) [ "$#" -eq 2 ] || uso; opus "$1" "$2" ;;
  juntar) [ "$#" -ge 3 ] || uso; juntar "$@" ;;
  duracao) [ "$#" -eq 1 ] || uso; duracao "$1" ;;
  *) uso ;;
esac
