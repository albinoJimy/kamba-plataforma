"""O modulo `social` do Assistente do Dono (KAM-121): perfil, calendario e legendas.

| Ficheiro | O que tem |
|---|---|
| `regras.py` | o perfil de marca, a semana ISO, a agenda em `Africa/Luanda`, os temas, as referencias e os botoes |
| `politicas.py` | o lexicon de marcadores pt-BR e a politica de alegacoes (`policy/`), selados por versao |
| `numeros.py` | a guarda dos numeros de uma legenda contra os factos do dono |
| `geracao.py` | a porta do gerador (`social-text`, por ligar) e as barreiras depois dele |
| `repositorio.py` | o contrato do estado e a versao em memoria; a de SQL e `../tls/social.py` |

As tools estao em `../tls/social_tools.py`, e a conversa em
`../verticais/dono/social.py`. **Nada deste modulo publica nem envia**: o dono
publica a mao (D13), e a aprovacao e a entrega sao do KAM-122.
"""
