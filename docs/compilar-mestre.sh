#!/usr/bin/env bash
# Regenera docs/00-KAMBA-documento-mestre.md a partir de docs/exploracao/*.md
# Uso: bash docs/compilar-mestre.sh   (fonte de verdade = ficheiros individuais)
set -euo pipefail
cd "$(dirname "$0")"
{
cat <<'EOF'
# KAMBÁ — Documento Mestre
## Plataforma AI-first de comércio conversacional para Angola

> Documento consolidado da biblioteca de exploração.
> Gerado por `docs/compilar-mestre.sh` — NÃO EDITAR À MÃO.
> Fonte de verdade = ficheiros individuais em `docs/exploracao/`.
> Excluído: 09 (arquitetura v1, desatualizada). Ver também `docs/tecnica/` (conjunto formal).
> 👉 Não sabes por onde começar? Lê a PARTE 13 (big picture) e volta ao início.

## Índice

- **PARTE 01** — Modelo de negócios: os 10 negócios adaptados a Angola (AI-first)
- **PARTE 02** — Enquadramento em plataforma (agência → plataforma → marketplace)
- **PARTE 03** — Modelo Google: atenção gratuita, intenção paga
- **PARTE 04** — Pontos cegos, ronda 1 (stress-test)
- **PARTE 05** — Estratégia: loja no WhatsApp + fluxo dual (número plataforma e/ou PME)
- **PARTE 06** — Expansões da plataforma (5 camadas)
- **PARTE 07** — Pontos cegos, ronda 2 (stress-test + 8 validações)
- **PARTE 08** — Arquitetura técnica v2 (o produto) — exploratória
- **PARTE 10** — Arquitetura de plataforma holística (a visão) — exploratória
- **PARTE 11** — Desenho detalhado de engenharia (o como) — exploratória
- **PARTE 12** — Diagramas C4 e fluxogramas (o visual)
- **PARTE 13** — Big picture do ecossistema (core · verticais · integrações · governação)
- **PARTE 14** — Tese mínima e plano de validação (escopo do Piloto)

---

EOF

for part in 01 02 03 04 05 06 07 08 10 11 12 13 14; do
  f=$(ls exploracao/${part}-*.md 2>/dev/null | head -1)
  [ -z "$f" ] && continue
  title=$(basename "$f" .md | sed "s/^${part}-//")
  printf '\n\n<!-- ============================================================ -->\n'
  printf '# 📘 PARTE %s — %s\n\n' "$part" "$title"
  cat "$f"
  printf '\n\n---\n'
done
} > 00-KAMBA-documento-mestre.md
echo "mestre regenerado: $(wc -c < 00-KAMBA-documento-mestre.md) bytes, $(grep -c '^# 📘 PARTE' 00-KAMBA-documento-mestre.md) partes"
