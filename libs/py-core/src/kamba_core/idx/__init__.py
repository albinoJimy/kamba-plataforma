"""`kamba_core.idx` — o lado Python do indice de pesquisa (KAM-061).

| Modulo | Decide |
|---|---|
| `texto` | a normalizacao comum ao indice e a consulta, e o *lint* do texto de embedding |
| `pesquisa` | a camada de resposta do §6.3: candidatos do indice juntos a oferta viva |
| `consumidor` | o efeito de `catalog.product_changed` e dos eventos de estado do tenant |

O DDL e a funcao `idx.candidatos` estao em `db/indice.py`, que e o modulo que a
revisao de base de dados chama. Aqui so ha SQL de **leitura e escrita de
linhas**, em constantes, que a suite do *gate* 8 importa e corre.
"""
