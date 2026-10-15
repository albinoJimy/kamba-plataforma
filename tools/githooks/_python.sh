# Encontra um interpretador Python que **funcione**, nao apenas um que exista.
#
# Em Windows, `command -v python3` encontra o atalho da Microsoft Store: um
# ficheiro que existe e que, ao ser corrido, imprime "Python nao foi encontrado"
# e falha. Testar com `command -v` dava-o por valido e o hook morria com uma
# mensagem que nao tem nada a ver com o commit. Testa-se a executar.
#
# Carregado pelos hooks com `. "$ROOT/tools/githooks/_python.sh"`.

kamba_find_python() {
  if [ -n "${PYTHON:-}" ]; then
    if "$PYTHON" -c "" >/dev/null 2>&1; then
      echo "$PYTHON"
      return 0
    fi
    echo "kamba: PYTHON=$PYTHON esta definido mas nao executa" >&2
    return 1
  fi

  for candidato in python3 python py; do
    if "$candidato" -c "" >/dev/null 2>&1; then
      echo "$candidato"
      return 0
    fi
  done

  cat >&2 <<'SEM_PYTHON'
kamba: nao encontrei um Python que funcione (tentei python3, python, py).

  Os git hooks validam as convencoes do §5 do Engineering Standards com
  tools/lint_arch, que depende apenas da biblioteca padrao do Python.

  Instale o Python 3.12, ou aponte PYTHON para o executavel:
      PYTHON=/caminho/para/python git commit ...
SEM_PYTHON
  return 1
}
