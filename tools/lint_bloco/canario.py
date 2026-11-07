"""O canario: prova que a regra **morde**, e que uma arvore limpa passa.

Um *lint* que nunca se viu falhar nao se sabe se funciona. Este monta arvores
minimas em pasta temporaria — uma por caso — e exige:

* cada **negativa** da o achado da sua regra, e so esse;
* cada **positiva** da zero achados;
* **todas** as regras de `REGRAS_OBRIGATORIAS` sao exercitadas por alguma
  negativa. A lista vem do **codigo** e nao das *fixtures*: um manifesto vazio
  nao pode dar «tudo verde», que e a disciplina do `obs_lint` e do `canon_lint`.

As arvores sao de dois blocos, e os pisos de cobertura passam baixos — ver a
nota em `lint.MINIMO_DE_BLOCOS_MEDIDOS`.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from lint_bloco import lint

#: Um bloco limpo: tres critérios, duas linhas de DoD, e as duas tabelas a
#: dizer o mesmo que as caixas.
LIMPO = """## KAM-001 — Um bloco que bate

| Campo | Valor |
|---|---|
| Fase | 0 |

### Critérios de Aceitação
- [x] O primeiro, que esta feito.
- [ ] O segundo, que nao esta.
- [x] O terceiro, que esta.

### Definition of Done
- [x] A documentacao esta actualizada.
- [ ] Todos os critérios satisfeitos.

### Verificação dos Critérios de Aceitação

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | O primeiro | **satisfeito** | medido |
| 2 | O segundo | **parcial** | falta a metade da sonda |
| 3 | O terceiro | **marcada** | medido |

| # | DoD | Estado | Evidência |
|---|---|---|---|
| 1 | Documentacao | **satisfeito** | medido |
| 2 | Todos os critérios | **não satisfeito** | o segundo nao esta |
"""

#: Um segundo bloco limpo, para a arvore nao ter so um.
LIMPO_2 = """## KAM-002 — Outro que bate, com tabela combinada

### Critérios de Aceitação
- [ ] Um critério por cumprir.

### Definition of Done
- [ ] Uma linha de DoD por cumprir.

### Verificação dos Critérios de Aceitação

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | O critério | **vazia** | devolvido, com credor |
| 2 | A DoD | **parcial** | idem |
"""


def _negativas() -> dict[str, tuple[str, str]]:
    """`nome -> (texto do bloco, regra que tem de morder)`."""
    return {
        # A caixa por marcar e a tabela a dizer `satisfeito`: **o escape que
        # este lint existe para fechar**, na forma exacta em que apareceu.
        "caixa_por_marcar_com_estado_satisfeito": (
            LIMPO.replace("- [x] O primeiro, que esta feito.",
                          "- [ ] O primeiro, que esta feito."),
            "estado_contra_caixa"),
        # O simetrico, que a contagem sozinha nao distingue do de cima.
        "caixa_marcada_com_estado_parcial": (
            LIMPO.replace("- [ ] O segundo, que nao esta.",
                          "- [x] O segundo, que nao esta."),
            "estado_contra_caixa"),
        # **A troca.** As duas caixas mudam, a contagem fica igual, e um lint
        # que comparasse totais dizia «conforme». Daí a comparacao ser par a par.
        "duas_caixas_trocadas_entre_si": (
            LIMPO.replace("- [x] O primeiro, que esta feito.",
                          "- [ ] O primeiro, que esta feito.")
                 .replace("- [ ] O segundo, que nao esta.",
                          "- [x] O segundo, que nao esta."),
            "estado_contra_caixa"),
        # A tabela da DoD a discordar da sua lista, e nao a dos critérios: sem
        # isto, um lint que so olhasse a primeira tabela ficava verde.
        "a_tabela_da_dod_e_que_discorda": (
            LIMPO.replace("| 1 | Documentacao | **satisfeito** | medido |",
                          "| 1 | Documentacao | **parcial** | medido |"),
            "estado_contra_caixa"),
    }


def _positivas() -> dict[str, str]:
    """`nome -> texto do bloco`. Casos que **tem** de passar."""
    return {
        # O vocabulario sem classe nao e achado: `nao aplicavel` com a caixa
        # marcada e legitimo, e foi um achado falso que o mostrou.
        "estado_sem_classe_nao_e_achado": LIMPO.replace(
            "| 2 | O segundo | **parcial** | falta a metade da sonda |",
            "| 2 | O segundo | **não aplicável** | nao se aplica a este canal |"),
        # A tabela combinada (critérios **e** DoD numa so) e uma das duas
        # convencoes da arvore, e nao se le como «linhas a mais».
        "tabela_combinada_criterios_e_dod": """## KAM-001 — Tabela combinada

### Critérios de Aceitação
- [x] Um que esta feito.
- [ ] Outro que nao esta.

### Definition of Done
- [x] Uma linha de DoD feita.

### Verificação dos Critérios de Aceitação

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | Um | **satisfeito** | medido |
| 2 | Outro | **vazia** | devolvido |
| 3 | A DoD | **satisfeito** | medido |
""",
        # Uma caixa dentro de uma **cerca** nao e uma caixa.
        #
        # **A primeira versao desta positiva nao provava nada**, e a revisao
        # adversarial mediu-o: as caixas cercadas estavam sob
        # `### Handoff para Claude Code`, uma seccao que nao e nenhuma das duas
        # listas — pelo que elas nunca entrariam na contagem, com cerca ou sem
        # ela. A mutacao que **desliga** o salto de cercas sobrevivia.
        #
        # Agora a cerca esta **dentro** da lista de critérios, que e onde ela tem
        # de morder: sem o salto, as duas linhas cercadas entram na lista, passam
        # a ser 5 caixas contra 3 linhas de tabela, e o bloco deixa de emparelhar.
        "caixa_dentro_de_cerca_nao_conta": LIMPO.replace(
            "- [x] O terceiro, que esta.",
            """- [x] O terceiro, que esta.

Um exemplo do que o critério pede, em cerca:

```text
- [ ] Uma caixa que esta dentro da cerca e nao e uma caixa.
- [x] Outra, idem.
```"""),
        # Um bloco **sem** tabela de verificacao nao e achado: e um ticket que
        # ainda nao foi entregue.
        "bloco_sem_tabela_de_verificacao": """## KAM-001 — Por entregar

### Critérios de Aceitação
- [ ] Um critério.

### Definition of Done
- [ ] Uma linha de DoD.
""",
    }


def _arvore(destino: Path, primeiro: str, segundo: str = LIMPO_2) -> None:
    (destino / "specs" / "tickets").mkdir(parents=True)
    (destino / "specs" / "EPIC-01_Fundacoes.md").write_text(
        "# EPIC-01\n\n" + primeiro, encoding="utf-8")
    (destino / "specs" / "tickets" / "KAM-002.md").write_text(
        segundo, encoding="utf-8")


def correr(verboso: bool = True) -> int:
    """0 se todas as negativas mordem e todas as positivas passam."""
    falhou = False
    exercitadas: set[str] = set()

    for nome, (texto, regra) in _negativas().items():
        raiz = Path(tempfile.mkdtemp(prefix="lint-bloco-neg-"))
        try:
            _arvore(raiz, texto)
            achados, _, _ = lint.verificar(raiz, minimo_blocos=2,
                                           minimo_medidos=1)
            regras = {a.regra for a in achados}
            if regra not in regras:
                falhou = True
                print(f"canario: a negativa {nome!r} NAO mordeu "
                      f"{regra!r} (deu {sorted(regras) or 'nada'})",
                      file=sys.stderr)
            else:
                exercitadas.add(regra)
                if regras - {regra}:
                    falhou = True
                    print(f"canario: a negativa {nome!r} mordeu de mais: "
                          f"{sorted(regras)}", file=sys.stderr)
        finally:
            shutil.rmtree(raiz, ignore_errors=True)

    for nome, texto in _positivas().items():
        raiz = Path(tempfile.mkdtemp(prefix="lint-bloco-pos-"))
        try:
            _arvore(raiz, texto)
            achados, _, _ = lint.verificar(raiz, minimo_blocos=2,
                                           minimo_medidos=1)
            if achados:
                falhou = True
                print(f"canario: a positiva {nome!r} deu achados: "
                      f"{[str(a) for a in achados]}", file=sys.stderr)
        finally:
            shutil.rmtree(raiz, ignore_errors=True)

    em_falta = set(lint.REGRAS_OBRIGATORIAS) - exercitadas
    if em_falta:
        falhou = True
        print(f"canario: regras sem negativa que as exercite: "
              f"{sorted(em_falta)}", file=sys.stderr)

    if verboso and not falhou:
        print(f"lint_bloco canario: {len(_negativas())} negativas, "
              f"{len(_positivas())} positivas")
        print("lint_bloco canario: todas mordem, e as positivas passam")
    return 1 if falhou else 0
