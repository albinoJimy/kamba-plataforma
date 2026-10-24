set -u
corepack enable >/dev/null 2>&1
cd /w
echo "--- build"; pnpm run build 2>&1 | tail -4
echo "--- typecheck"; pnpm -r run typecheck 2>&1 | grep -Ei "error|Done|Failed" | head -20
echo "--- testes"
for pacote in packages/contracts packages/core-ts services/gwy services/worker-canal services/com services/onboarding-web tools/meta-sim; do
  nome=$(echo "$pacote" | tr "/" "-")
  lista="/w/ci/coverage/excluidos-$nome.txt"
  python3 /w/tools/coverage_gate.py --root /w --exclusoes-node "$pacote" > "$lista" 2>/dev/null || : > "$lista"
  excluir=$(sed "s|^|--test-coverage-exclude=|" "$lista" | tr "\n" " ")
  if (cd "/w/$pacote" && node --test --experimental-test-coverage $excluir --test-reporter=tap --test-reporter-destination=stdout --test-reporter=lcov --test-reporter-destination="/w/ci/coverage/node-$nome.lcov" tests/*.test.ts) > "/w/ci/coverage/node-$nome.log" 2>&1; then
    echo "OK   $pacote"
  else
    echo "FALHA $pacote"; grep -n "^not ok" "/w/ci/coverage/node-$nome.log" | head -5
  fi
done
