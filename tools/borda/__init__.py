"""A borda do *host* (KAM-077): a sonda de RTT e as regras de *firewall* do *host*.

Duas coisas que o KAM-077 pede e que se preparam **sem a D1**:

* `rtt` — a sonda que mede o RTT de Luanda ao *host* e do *host* a
  `graph.facebook.com` durante 24 h, e o relatorio que **recusa** sair sem
  numeros medidos (criterio 5 e 3.o Teste Requerido do bloco);
* `firewall` — a verificacao das regras `nftables` que o `host-base` escreve
  (criterio 4; classe 3 de `infra/PORTABILIDADE.md`).

Nenhuma das duas mediu um *host*: nao ha *host* ate a D1 fechar.
"""
