"""As verticais: um pacote por grafo de negocio (ADR-012).

O `registry/vendedor.yaml` aponta o `graph` para `kamba_agr.verticais.vendedor:
build_graph` e o de Servicos aponta para `kamba_agr.verticais.servicos`, que e o
KAM-035. O alvo era *proposta* do KAM-027 — «quem o ratifica e o KAM-031, que
escreve o modulo» — e este pacote e a ratificacao.

**Nao ha codigo partilhado aqui, e isso e desenho.** A «regra de dois» do
`docs/tecnica/02` §5.4 diz que o partilhado vive no core (`estado.py`,
`turno.py`, `tls/`, `validador/`, `llm/`) e que a vertical traz so o que e seu —
o grafo, os nos especificos e as tools. Um modulo de conveniencia aqui era o
primeiro sitio onde uma excepcao de vertical se esconderia, e o gate da Fase 0
mede exactamente isso: «nenhuma excepcao no core (`grep` de nomes de vertical em
`core/` = 0)».
"""
