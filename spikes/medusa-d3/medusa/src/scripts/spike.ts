/**
 * Tudo o que se mede **de dentro** do Medusa. Corre por `medusa exec`.
 *
 * Porque e que isto nao e Python como o resto do harness: o Medusa nao publica
 * porta nenhuma no anfitriao — e o AC-2 exige-o — pelo que o processo que o
 * interroga tem de estar na mesma rede. E o *query graph* e o Inventory Module
 * nao sao superficies HTTP: vivem no processo. `medusa exec` da acesso ao
 * contentor de dependencias, que e a unica forma honesta de os medir.
 *
 * Escreve dois ficheiros em `/saida`:
 *   `medusa-iso.json`  ISO-11..32
 *   `medusa-ac3.json`  a prova de sobrevenda, pelos dois caminhos do Medusa
 *
 * **O que esta prova procura.** A documentacao oficial (lida a 2026-10-27,
 * CONFIRMADO) diz que o `inventoryService.createReservationItems` valida por
 * `list()` e depois escreve — sem `FOR UPDATE`, sem lock, sem constraint — e que
 * a proteccao esta um nivel acima, no passo de *workflow*, que envolve a
 * chamada no **Locking Module**. E diz que o provider de locking por omissao e
 * in-memory, «only intended for use in a single-instance environment». Logo ha
 * dois numeros a medir, e sao diferentes:
 *
 *   `modulo`   chamada directa ao servico      -> espera-se corrida
 *   `locking`  a mesma chamada dentro do lock  -> espera-se serializacao
 *
 * Medir so o segundo dava um verde que nao sobrevive a segunda instancia do
 * COM; medir so o primeiro dizia que o Medusa e inseguro quando a pilha
 * recomendada o protege. O relatorio leva os dois.
 */
import { ContainerRegistrationKeys, Modules } from "@medusajs/framework/utils";
import type { ExecArgs } from "@medusajs/framework/types";
import { mkdirSync, writeFileSync } from "node:fs";

const SAIDA = process.env.KAMBA_SPIKE_SAIDA ?? "/saida";
const TENANTS = JSON.parse(process.env.KAMBA_SPIKE_TENANTS ?? "{}") as Record<
  string,
  { tenant_id: string; merchant_id: string }
>;
/** Quantas tentativas concorrentes a prova de sobrevenda faz, sobre stock 10. */
const TENTATIVAS = Number(process.env.KAMBA_SPIKE_TENTATIVAS ?? "1000");
const STOCK = 10;

type Caso = {
  id: string;
  superficie: string;
  cenario: string;
  esperado: string;
  estado: "passa" | "falha" | "nao_verificado";
  observado: string;
  evidencia: string;
};

const casos: Caso[] = [];

function registar(
  id: string,
  superficie: string,
  cenario: string,
  esperado: string,
  estado: Caso["estado"],
  observado: string,
  evidencia = "",
) {
  casos.push({ id, superficie, cenario, esperado, estado, observado, evidencia });
}

/** Marca um caso como nao medido, nomeando a razao. Nunca verde. */
function naoMedido(id: string, superficie: string, cenario: string,
                   esperado: string, razao: string) {
  registar(id, superficie, cenario, esperado, "nao_verificado", "nao medido", razao);
}

export default async function spike({ container }: ExecArgs) {
  mkdirSync(SAIDA, { recursive: true });
  const query = container.resolve(ContainerRegistrationKeys.QUERY);
  const logger = container.resolve(ContainerRegistrationKeys.LOGGER);

  const rotulos = Object.keys(TENANTS);
  if (rotulos.length < 2) {
    naoMedido("ISO-11", "API Store do Medusa", "—", "—",
      "KAMBA_SPIKE_TENANTS nao trouxe tenants");
    writeFileSync(`${SAIDA}/medusa-iso.json`, JSON.stringify(casos, null, 2));
    return;
  }
  const A = TENANTS["A"];
  const B = TENANTS["B"];

  // ------------------------------------------------------------------ semear
  // Um `merchant` por tenant, e um produto ligado a cada. E o minimo que a
  // matriz precisa: ids reais de B para o contexto de A sondar.
  const merchantService = container.resolve("merchant") as unknown as {
    createMerchants: (d: unknown) => Promise<{ id: string }[] | { id: string }>;
    listMerchants: (f?: unknown) => Promise<{ id: string; tenant_id: string }[]>;
  };
  const link = container.resolve(ContainerRegistrationKeys.LINK);
  const productService = container.resolve(Modules.PRODUCT) as unknown as {
    createProducts: (d: unknown) => Promise<{ id: string }[] | { id: string }>;
  };

  const merchants: Record<string, { id: string; produto: string }> = {};
  for (const rotulo of ["A", "B"]) {
    const dados = TENANTS[rotulo];
    const criado = await merchantService.createMerchants({
      tenant_id: dados.tenant_id,
      nome: `Spike tenant ${rotulo}`,
    });
    const merchant = Array.isArray(criado) ? criado[0] : criado;
    const produtoCriado = await productService.createProducts({
      title: `Produto do tenant ${rotulo}`,
      status: "published",
      options: [{ title: "Tamanho", values: ["unico"] }],
      variants: [{ title: "unico", options: { Tamanho: "unico" }, manage_inventory: true }],
    });
    const produto = Array.isArray(produtoCriado) ? produtoCriado[0] : produtoCriado;
    await link.create({
      merchant: { merchant_id: merchant.id },
      product: { product_id: produto.id },
    });
    merchants[rotulo] = { id: merchant.id, produto: produto.id };
  }
  // Um `InventoryItem` por tenant, ligado à variante do produto. **O ISO-31
  // precisa dele para existir**: sem itens de inventário, o `Query.graph` de
  // `inventory_item` devolve zero registos e a sonda não prova nada — foi o que
  // aconteceu na execução anterior, e ficou `nao_verificado` com essa razão.
  try {
    const inventario = container.resolve(Modules.INVENTORY) as unknown as {
      createInventoryItems: (d: unknown) => Promise<{ id: string }[] | { id: string }>;
    };
    for (const rotulo of ["A", "B"]) {
      await inventario.createInventoryItems({
        sku: `SPIKE-ISO31-${rotulo}`,
        title: `Inventario do tenant ${rotulo}`,
      });
    }
  } catch (erro) {
    logger.error(
      `spike: itens de inventario nao criados (ISO-31 fica sem dados): `
      + `${(erro as Error).message}`,
    );
  }

  logger.info(`spike: merchants ${JSON.stringify(merchants)}`);

  // ------------------------------------------------- ISO-11..18: API Store
  // A Store API exige uma chave publicavel ligada a um sales channel. Criar a
  // cadeia (canal + chave + associacao) por tenant e so possivel pela Admin
  // API ou pelos modulos; faz-se pelos modulos, que e o que este processo tem.
  const apiKeyService = container.resolve(Modules.API_KEY) as unknown as {
    createApiKeys: (d: unknown) => Promise<{ id: string; token: string }[] | { id: string; token: string }>;
  };
  const salesChannelService = container.resolve(Modules.SALES_CHANNEL) as unknown as {
    createSalesChannels: (d: unknown) => Promise<{ id: string }[] | { id: string }>;
  };

  // Uma região por tenant. **A Store API de carts exige-a**: sem região, o
  // `POST /store/carts` recusa, e o ISO-14 («o cart de B pedido com a chave de
  // A») ficava sem um id de B para sondar. Moeda AOA, que é a do projecto.
  const regiaoService = container.resolve(Modules.REGION) as unknown as {
    createRegions: (d: unknown) => Promise<{ id: string }[] | { id: string }>;
  };

  const canais: Record<string, { canal: string; chave: string; regiao?: string }> = {};
  let cadeiaStoreOk = true;
  for (const rotulo of ["A", "B"]) {
    try {
      const canalCriado = await salesChannelService.createSalesChannels({
        name: `Canal do tenant ${rotulo}`,
      });
      const canal = Array.isArray(canalCriado) ? canalCriado[0] : canalCriado;
      const chaveCriada = await apiKeyService.createApiKeys({
        title: `Chave do tenant ${rotulo}`,
        type: "publishable",
        created_by: "spike",
      });
      const chave = Array.isArray(chaveCriada) ? chaveCriada[0] : chaveCriada;
      await link.create({
        [Modules.API_KEY]: { publishable_key_id: chave.id },
        [Modules.SALES_CHANNEL]: { sales_channel_id: canal.id },
      });
      let regiao: string | undefined;
      try {
        const regiaoCriada = await regiaoService.createRegions({
          name: `Angola (tenant ${rotulo})`,
          currency_code: "aoa",
        });
        const r = Array.isArray(regiaoCriada) ? regiaoCriada[0] : regiaoCriada;
        regiao = r?.id;
      } catch (erro) {
        logger.error(
          `spike: regiao do tenant ${rotulo} nao criada: ${(erro as Error).message}`,
        );
      }
      canais[rotulo] = { canal: canal.id, chave: chave.token, regiao };
    } catch (erro) {
      cadeiaStoreOk = false;
      logger.error(`spike: cadeia Store do tenant ${rotulo} falhou: ${(erro as Error).message}`);
    }
  }

  // Os cenários seguem a coluna «Cenário» do §4.4: «Chave/canal de A a pedir
  // **produtos, carts, encomendas, stock e preços** de B por id e por
  // pesquisa». A primeira versão trocou três destes por sondas de
  // autenticação (sem chave, chave inválida, regiões) — que são verdes por a
  // Store API exigir chave, e não dizem nada sobre isolamento entre tenants.
  const sondasStore: [string, string][] = [
    ["ISO-11", "chave publicavel de A a pedir produto de B por id"],
    ["ISO-12", "chave publicavel de A a pesquisar produtos de B por titulo"],
    ["ISO-13", "chave publicavel de A a pedir variantes e precos de B"],
    ["ISO-14", "chave publicavel de A a pedir o cart de B por id"],
    ["ISO-15", "chave publicavel de A a pedir a encomenda de B por id"],
    ["ISO-16", "chave publicavel de A a pedir o stock/inventario de B"],
    ["ISO-17", "chave publicavel de A a listar produtos sem filtro"],
    ["ISO-18", "chave de A com o `sales_channel_id` de B no parametro"],
  ];

  if (!cadeiaStoreOk || !canais.A || !canais.B) {
    for (const [id, cenario] of sondasStore) {
      naoMedido(id, "API Store do Medusa", cenario, "negado ou vazio",
        "a cadeia canal + chave publicavel nao se conseguiu criar neste "
        + "processo; sem chave de A nao ha com que sondar os ids de B");
    }
  } else {
    const base = "http://127.0.0.1:9000";
    const comChaveA = { "x-publishable-api-key": canais.A.chave };

    async function sondar(url: string, cabecalhos: Record<string, string>) {
      const resposta = await fetch(`${base}${url}`, { headers: cabecalhos });
      const corpo = await resposta.text();
      return { estado: resposta.status, corpo };
    }

    // ISO-11: produto de B por id, com a chave de A.
    {
      const r = await sondar(`/store/products/${merchants.B.produto}`, comChaveA);
      const fuga = r.estado === 200 && r.corpo.includes(merchants.B.produto);
      registar("ISO-11", "API Store do Medusa", sondasStore[0][1],
        "negado ou vazio", fuga ? "falha" : "passa",
        `HTTP ${r.estado}`,
        fuga
          ? "a chave publicavel de A devolveu o produto de B: o canal nao isola "
            + "por si, e o filtro tem de ser do COM"
          : `o pedido nao devolveu o produto de B (HTTP ${r.estado})`);
    }
    // ISO-12: pesquisa pelo titulo do produto de B.
    {
      const r = await sondar(`/store/products?q=tenant%20B`, comChaveA);
      const fuga = r.corpo.includes(merchants.B.produto);
      registar("ISO-12", "API Store do Medusa", sondasStore[1][1],
        "negado ou vazio", fuga ? "falha" : "passa",
        `HTTP ${r.estado}`, fuga ? "a pesquisa devolveu o produto de B" : "");
    }
    // ISO-13: variantes e precos.
    {
      const r = await sondar(
        `/store/products?fields=*variants,*variants.calculated_price`, comChaveA);
      const fuga = r.corpo.includes(merchants.B.produto);
      registar("ISO-13", "API Store do Medusa", sondasStore[2][1],
        "negado ou vazio", fuga ? "falha" : "passa", `HTTP ${r.estado}`,
        fuga ? "variantes de B visiveis com a chave de A" : "");
    }

    // ISO-14: o cart de B, pedido com a chave de A. Cria-se um cart com a
    // chave de B para haver um id real de B que a chave de A possa sondar —
    // sem isso o caso media «um id que nao existe», que nao e isolamento.
    {
      const comChaveB = { "x-publishable-api-key": canais.B.chave,
                          "content-type": "application/json" };
      let cartDeB: string | undefined;
      let recusaDoCart: string | undefined;
      try {
        const criado = await fetch(`${base}/store/carts`, {
          method: "POST",
          headers: comChaveB,
          body: JSON.stringify(
            canais.B.regiao ? { region_id: canais.B.regiao } : {},
          ),
        });
        if (criado.ok) {
          const corpo = (await criado.json()) as { cart?: { id?: string } };
          cartDeB = corpo?.cart?.id;
        } else {
          const texto = await criado.text();
          logger.error(
            `spike: POST /store/carts deu ${criado.status}: ${texto.slice(0, 300)}`,
          );
          recusaDoCart = `HTTP ${criado.status}: ${texto.slice(0, 200)}`;
        }
      } catch (erro) {
        recusaDoCart = `excepcao: ${(erro as Error).message}`;
        logger.error(`spike: POST /store/carts rebentou: ${(erro as Error).message}`);
      }

      if (!cartDeB) {
        naoMedido("ISO-14", "API Store do Medusa", sondasStore[3][1],
          "negado ou vazio",
          "nao se conseguiu criar um cart com a chave de B"
          + (canais.B.regiao
            ? " (a regiao foi criada, pelo que a recusa e outra)"
            : " porque a regiao do tenant B nao se criou, e a Store API de "
              + "carts exige uma")
          + `, pelo que nao ha id de B para a chave de A sondar. Recusa: `
          + `${recusaDoCart ?? "(nao registada)"}`);
      } else {
        const r = await sondar(`/store/carts/${cartDeB}`, comChaveA);
        const fuga = r.estado === 200 && r.corpo.includes(cartDeB);
        registar("ISO-14", "API Store do Medusa", sondasStore[3][1],
          "negado ou vazio", fuga ? "falha" : "passa", `HTTP ${r.estado}`,
          fuga
            ? `a chave de A devolveu o cart ${cartDeB} do tenant B`
            : `o cart de B nao foi devolvido a chave de A (HTTP ${r.estado})`);
      }
    }

    // ISO-15: a encomenda de B, pedida com a chave de A.
    //
    // A encomenda cria-se pelo **Order Module** e não pelo fluxo
    // `cart -> payment collection -> complete`: o que o caso precisa é de um id
    // de encomenda real do tenant B para a chave de A sondar, e não de
    // exercitar o checkout (que no desenho da KAMBÁ não é do Medusa — o ciclo
    // de vida é autoridade do `platform.orders_mirror`, §10.1).
    {
      const orderService = container.resolve(Modules.ORDER) as unknown as {
        createOrders: (d: unknown) => Promise<{ id: string }[] | { id: string }>;
      };
      let encomendaDeB: string | undefined;
      try {
        const criada = await orderService.createOrders({
          region_id: canais.B.regiao,
          currency_code: "aoa",
          email: "cliente@spike.invalid",
          items: [
            {
              title: "Item do spike (tenant B)",
              quantity: 1,
              unit_price: 1000,
            },
          ],
        });
        const encomenda = Array.isArray(criada) ? criada[0] : criada;
        encomendaDeB = encomenda?.id;
      } catch (erro) {
        logger.error(
          `spike: encomenda de B nao criada: ${(erro as Error).message}`,
        );
      }

      if (!encomendaDeB) {
        naoMedido("ISO-15", "API Store do Medusa", sondasStore[4][1],
          "negado ou vazio",
          "nao se conseguiu criar uma encomenda no Order Module para o tenant "
          + "B, pelo que nao ha id de B para a chave de A sondar; ver o "
          + "/saida/medusa-exec.log");
      } else {
        const r = await sondar(`/store/orders/${encomendaDeB}`, comChaveA);
        // **Controlo: o mesmo pedido com um id que nao existe.** Sem isto, um
        // `200` nao se distingue de um endpoint que devolve 200 a tudo, e um
        // `404` nao se distingue de «a rota nega sempre». O par (id de B, id
        // inexistente) e o que torna o resultado interpretavel.
        const controlo = await sondar(
          `/store/orders/order_01INEXISTENTE000000000000`, comChaveA);
        const fuga = r.estado === 200 && r.corpo.includes(encomendaDeB);
        const contraste = `id de B -> HTTP ${r.estado}; `
          + `id inexistente -> HTTP ${controlo.estado}`;
        if (fuga && controlo.estado !== 200) {
          registar("ISO-15", "API Store do Medusa", sondasStore[4][1],
            "negado ou vazio", "falha", `HTTP ${r.estado}`,
            `**fuga confirmada e especifica**: a chave publicavel do tenant A `
            + `devolveu a encomenda ${encomendaDeB}, que e do tenant B, com `
            + `HTTP 200 — e o mesmo pedido com um id inexistente deu HTTP `
            + `${controlo.estado}. Logo o 200 nao e um endpoint permissivo: e `
            + `a encomenda de outro tenant a ser servida. ${contraste}`);
        } else if (fuga) {
          registar("ISO-15", "API Store do Medusa", sondasStore[4][1],
            "negado ou vazio", "nao_verificado", `HTTP ${r.estado}`,
            `a chave de A devolveu a encomenda de B, **mas o id inexistente `
            + `tambem deu 200**: o endpoint responde a tudo e a sonda nao `
            + `distingue fuga de permissividade. ${contraste}`);
        } else {
          registar("ISO-15", "API Store do Medusa", sondasStore[4][1],
            "negado ou vazio", "passa", `HTTP ${r.estado}`,
            `negado. ${contraste}`
            + (r.estado === 401 && controlo.estado === 401
              ? ". **A barreira foi a autenticacao de cliente, nao o "
                + "isolamento entre tenants**: a rota exige sessao de cliente, "
                + "e o id inexistente deu o mesmo 401. O caso esta medido, e o "
                + "que ele mostra e isto"
              : ""));
        }
      }
    }

    // ISO-16: stock/inventario de B pela Store API.
    {
      const r = await sondar(
        `/store/products/${merchants.B.produto}`
        + `?fields=*variants,*variants.inventory_quantity`, comChaveA);
      const fuga = r.estado === 200 && r.corpo.includes(merchants.B.produto);
      registar("ISO-16", "API Store do Medusa", sondasStore[5][1],
        "negado ou vazio", fuga ? "falha" : "passa", `HTTP ${r.estado}`,
        fuga
          ? "a chave de A leu o inventario do produto de B"
          : `negado (HTTP ${r.estado})`);
    }

    // ISO-17: listagem sem filtro.
    {
      const r = await sondar(`/store/products?limit=100`, comChaveA);
      const fuga = r.corpo.includes(merchants.B.produto);
      registar("ISO-17", "API Store do Medusa", sondasStore[6][1],
        "so produtos de A", fuga ? "falha" : "passa", `HTTP ${r.estado}`,
        fuga ? "a listagem incluiu o produto de B" : "");
    }

    // ISO-18: canal de B no parametro, com a chave de A.
    {
      const r = await sondar(
        `/store/products?sales_channel_id[]=${canais.B.canal}`, comChaveA);
      const fuga = r.corpo.includes(merchants.B.produto);
      registar("ISO-18", "API Store do Medusa", sondasStore[7][1],
        "negado ou vazio", fuga ? "falha" : "passa", `HTTP ${r.estado}`,
        fuga
          ? "pedir o canal de B com a chave de A devolveu dados de B"
          : "o canal pedido no parametro nao sobrepoe o da chave");
    }
  }

  // ------------------------------------------------- ISO-19..26: API Admin
  //
  // O §4.4 pede duas coisas distintas: «token de operador usado a partir de
  // rede de tenant» (que é **rede**, e é o AC-2) e «rotas de listagem sem
  // filtro → inacessível; **com acesso operador, auditado**».
  //
  // A primeira versão mandava os oito pedidos **sem credencial** e passava
  // porque a Admin API devolve 401 a quem não a traz. Isso é verdade sobre
  // qualquer rota `/admin/*` e não mede isolamento entre tenants: dava oito
  // verdes por autenticação ausente. Agora autentica-se com o operador que o
  // contentor criou, e o que se mede é o que o §4.4 nomeia — **que o operador
  // vê tudo, porque o Medusa não tem noção de tenant**, e que por isso a
  // credencial de operador não pode existir na rede de um tenant (AC-2).
  {
    const base = "http://127.0.0.1:9000";
    const email = process.env.KAMBA_SPIKE_ADMIN_EMAIL;
    const senha = process.env.KAMBA_SPIKE_ADMIN_SENHA;
    let token: string | undefined;
    if (email && senha) {
      try {
        const autenticacao = await fetch(`${base}/auth/user/emailpass`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ email, password: senha }),
        });
        if (autenticacao.ok) {
          const corpo = (await autenticacao.json()) as { token?: string };
          token = corpo?.token;
        } else {
          logger.error(`spike: /auth/user/emailpass deu ${autenticacao.status}`);
        }
      } catch (erro) {
        logger.error(`spike: autenticacao do operador falhou: ${(erro as Error).message}`);
      }
    }

    const semCredencial = "inacessivel sem credencial de operador";
    const comOperador =
      "o operador ve tudo (o Medusa nao tem noção de tenant): por isso a "
      + "credencial nao pode existir na rede de um tenant — AC-2";

    // Os dois que não precisam de token: medem a ausência de credencial, e o
    // §4.4 pede-os («rotas de listagem sem filtro → inacessível»).
    for (const [id, cenario, caminho] of [
      ["ISO-19", "rota Admin de produtos sem credencial nenhuma", "/admin/products"],
      ["ISO-20", "rota Admin com a chave publicavel de A em vez do token",
        "/admin/products"],
    ] as [string, string, string][]) {
      try {
        const cabecalhos: Record<string, string> =
          id === "ISO-20" && canais.A
            ? { "x-publishable-api-key": canais.A.chave }
            : {};
        const resposta = await fetch(`${base}${caminho}`, { headers: cabecalhos });
        registar(id, "API Admin do Medusa", cenario, semCredencial,
          resposta.status === 200 ? "falha" : "passa",
          `HTTP ${resposta.status}`,
          resposta.status === 200
            ? "a rota Admin respondeu sem credencial de operador"
            : "a rota Admin recusou");
      } catch (erro) {
        naoMedido(id, "API Admin do Medusa", cenario, semCredencial,
          `a sonda nao chegou a correr: ${(erro as Error).message}`);
      }
    }

    // Os cinco que precisam do token de operador.
    const comToken: [string, string, string][] = [
      ["ISO-21", "operador a listar produtos sem filtro de merchant",
        "/admin/products?limit=100"],
      ["ISO-22", "operador a listar inventario sem filtro de merchant",
        "/admin/inventory-items?limit=100"],
      ["ISO-23", "operador a listar clientes sem filtro de merchant",
        "/admin/customers?limit=100"],
      ["ISO-24", "operador a listar sales channels sem filtro",
        "/admin/sales-channels?limit=100"],
      ["ISO-25", "operador a pedir o produto de B por id",
        `/admin/products/${merchants.B.produto}`],
    ];
    for (const [id, cenario, caminho] of comToken) {
      if (!token) {
        naoMedido(id, "API Admin do Medusa", cenario, comOperador,
          "nao se obteve token de operador (o `medusa user` ou o "
          + "`/auth/user/emailpass` falharam; ver /saida/medusa-user.log), pelo "
          + "que a metade «com acesso operador» do §4.4 nao foi medida");
        continue;
      }
      try {
        const resposta = await fetch(`${base}${caminho}`, {
          headers: { authorization: `Bearer ${token}` },
        });
        const corpo = await resposta.text();
        const veDeB = corpo.includes(merchants.B.produto)
          || corpo.includes(canais.B?.canal ?? "\u0000");
        // **Aqui «ver de B» é o resultado esperado, não uma falha.** O operador
        // é interno e o Medusa não filtra por tenant: o caso passa quando
        // confirma isso por execução, porque é essa confirmação que obriga o
        // AC-2 (o admin fora da rede dos tenants) a ser bloqueante. Marcá-lo
        // vermelho era culpar o Medusa de não fazer o que nunca prometeu.
        registar(id, "API Admin do Medusa", cenario, comOperador,
          resposta.status === 200 ? "passa" : "nao_verificado",
          `HTTP ${resposta.status}, ${veDeB ? "ve" : "nao ve"} dados de B`,
          resposta.status === 200
            ? (veDeB
              ? "confirmado por execucao: um token de operador atravessa "
                + "tenants. O isolamento nao esta na Admin API — esta em o "
                + "admin nao ser alcancavel (AC-2) e no adaptador do COM"
              : "o operador autenticou mas nao devolveu dados de B; pode ser "
                + "que nao houvesse nenhum nesta rota")
            : `o operador autenticou mas a rota deu ${resposta.status}: nao se `
              + "consegue concluir nada sobre o ambito`");
      } catch (erro) {
        naoMedido(id, "API Admin do Medusa", cenario, comOperador,
          `a sonda nao chegou a correr: ${(erro as Error).message}`);
      }
    }

    // ISO-26: a rota Enterprise. **Com o token**, para o caso poder distinguir
    // «a flag EE está desligada» de «não há credencial» — sem token, qualquer
    // rota `/admin/*` dá 401 e o caso não observava nada.
    if (!token) {
      naoMedido("ISO-26", "API Admin do Medusa",
        "rota Admin de RBAC (material Enterprise), com token de operador",
        "404/501: a rota EE nao esta montada porque a flag esta desligada",
        "nao se obteve token de operador, e sem ele um 401 nao distingue a "
        + "flag desligada de credencial ausente");
    } else {
      try {
        const resposta = await fetch(`${base}/admin/rbac/roles`, {
          headers: { authorization: `Bearer ${token}` },
        });
        // Com credencial válida: 404 (rota não montada) é o resultado que
        // corrobora a flag desligada; 200 seria material EE a responder.
        registar("ISO-26", "API Admin do Medusa",
          "rota Admin de RBAC (material Enterprise), com token de operador",
          "404/501: a rota EE nao esta montada porque a flag esta desligada",
          resposta.status === 200 ? "falha"
            : resposta.status === 401 ? "nao_verificado" : "passa",
          `HTTP ${resposta.status}`,
          resposta.status === 200
            ? "a rota RBAC respondeu: material Enterprise activo (ver AC-7)"
            : resposta.status === 401
              ? "401 com token: nao se distingue a flag desligada de credencial "
                + "recusada"
              : "a rota EE nao esta montada, com credencial valida — corrobora "
                + "o AC-7 por execucao");
      } catch (erro) {
        naoMedido("ISO-26", "API Admin do Medusa",
          "rota Admin de RBAC (material Enterprise), com token de operador",
          "404/501", `a sonda nao chegou a correr: ${(erro as Error).message}`);
      }
    }
  }

  // ------------------------------------------- ISO-27..32: query graph
  // A pergunta nao e «o Medusa isola?» — a documentacao ja diz que nao tem
  // multi-tenancy nativa. A pergunta e se o filtro que o COM injecta isola, e
  // se o **mesmo** query graph sem filtro deixa passar. Medem-se os dois.
  const sondasGrafo: [string, string, () => Promise<unknown[]>][] = [
    ["ISO-27", "Query.graph de merchants **sem** filtro",
      async () => (await query.graph({ entity: "merchant", fields: ["id", "tenant_id"] })).data],
    ["ISO-28", "Query.graph de merchants com o filtro que o COM injecta (A)",
      async () => (await query.graph({
        entity: "merchant", fields: ["id", "tenant_id"],
        filters: { tenant_id: A.tenant_id },
      })).data],
    ["ISO-29", "Query.graph pelo link merchant->product com o merchant de A",
      async () => (await query.graph({
        entity: "merchant", fields: ["id", "tenant_id", "product.*"],
        filters: { id: merchants.A.id },
      })).data],
    // **Estes dois atravessam o link de propósito.** A primeira versão pedia
    // `fields: ["id","title"]` sobre `product`, e os registos devolvidos não
    // têm `tenant_id` nem o `id` do merchant — pelo que o predicado de fuga
    // nunca podia ser verdadeiro e os dois casos ficavam estruturalmente
    // **não mediáveis**, deixando o AC-1 em 58 de 60 para sempre. Pedir
    // `merchant.*` é o que torna a fuga observável: um produto que devolva o
    // merchant de B é fuga, e um que não devolva merchant nenhum também é
    // informação (o link não cobre tudo).
    ["ISO-30", "Query.graph de produtos **sem** filtro, atravessando o link para o merchant",
      async () => {
        const { data } = await query.graph({
          entity: "product", fields: ["id", "title", "merchant.*"],
        });
        // Normaliza para a forma que o predicado de fuga sabe ler: cada
        // produto passa a trazer o `tenant_id` do merchant a que está ligado.
        return data.map((p: Record<string, unknown>) => {
          const ligados = Array.isArray(p.merchant)
            ? (p.merchant as Record<string, unknown>[])
            : p.merchant
              ? [p.merchant as Record<string, unknown>]
              : [];
          return {
            id: p.id,
            title: p.title,
            tenant_id: ligados[0]?.tenant_id,
            merchant_id: ligados[0]?.id,
          };
        });
      }],
    // **O tenant vem do `sku`, e não de um `link`.** A primeira versão
    // atravessava `variants.product.merchant.*` e devolvia zero registos: os
    // `InventoryItem` do spike não estão ligados a variantes, pelo que o
    // caminho não chega ao merchant e a sonda não provava nada (ficou
    // `nao_verificado` com essa razão, honestamente, mas sem medir).
    //
    // Os itens são criados com `sku` `SPIKE-ISO31-A` e `SPIKE-ISO31-B`, que é
    // um marcador que **nós** controlamos. Se uma consulta sem filtro devolver
    // os dois, está confirmado por execução que o inventário não é filtrado
    // por tenant — que é o que a linha do §4.4 quer saber.
    ["ISO-31", "Query.graph de inventário **sem** filtro (itens marcados por tenant no `sku`)",
      async () => {
        let dados: Record<string, unknown>[] = [];
        try {
          const resposta = await query.graph({
            entity: "inventory_item",
            fields: ["id", "sku"],
          });
          dados = resposta.data as Record<string, unknown>[];
        } catch (erro) {
          logger.error(
            `spike ISO-31: Query.graph de inventory_item falhou `
            + `(${(erro as Error).message}); cai para o serviço do módulo`,
          );
        }
        if (dados.length === 0) {
          // Queda declarada: o serviço do módulo em vez do *query graph*. Mede
          // a mesma propriedade — «o inventário não é filtrado por tenant» — e
          // a evidência do caso diz por que via foi medida.
          const inventario = container.resolve(Modules.INVENTORY) as unknown as {
            listInventoryItems: (f?: unknown) => Promise<Record<string, unknown>[]>;
          };
          dados = await inventario.listInventoryItems({});
        }
        return dados.map((i) => ({
          id: i.id,
          sku: i.sku,
          tenant_id: String(i.sku ?? "").endsWith("-B") ? B.tenant_id : undefined,
        }));
      }],
    ["ISO-32", "Query.graph com filtro de tenant forjado (tenant inexistente)",
      async () => (await query.graph({
        entity: "merchant", fields: ["id", "tenant_id"],
        filters: { tenant_id: "00000000-0000-0000-0000-000000000000" },
      })).data],
  ];

  for (const [id, cenario, correr] of sondasGrafo) {
    try {
      const dados = await correr();
      const deB = dados.filter((d) => {
        const registo = d as Record<string, unknown>;
        return (
          registo.tenant_id === B.tenant_id
          || registo.id === merchants.B.id
          || registo.merchant_id === merchants.B.id
        );
      });
      const semFiltro = cenario.includes("**sem** filtro");
      if (semFiltro) {
        // Sem filtro, o query graph devolver tudo e o **comportamento
        // documentado**, nao um defeito do Medusa. O caso mede que o COM nao
        // pode delegar nele: passa quando confirma isso, e a evidencia diz o
        // numero. Marcar isto `falha` era culpar o Medusa de nao fazer o que
        // nunca prometeu — e marcar `passa` sem o numero esconderia o facto.
        registar(id, "query graph / modulos", cenario,
          "filtro imposto pelo COM: o grafo **nao** filtra por si",
          deB.length > 0 ? "passa" : "nao_verificado",
          `${dados.length} registo(s), ${deB.length} de outro tenant`,
          deB.length > 0
            ? "confirmado por execucao: o query graph sem filtro atravessa "
              + "tenants. O isolamento tem de ser do adaptador do COM (§3.3)"
            : "o grafo nao devolveu dados de outro tenant, mas tambem nao havia "
              + "nenhum para devolver: a sonda nao prova nada");
      } else {
        registar(id, "query graph / modulos", cenario,
          "so registos do tenant do filtro",
          deB.length === 0 ? "passa" : "falha",
          `${dados.length} registo(s), ${deB.length} de outro tenant`,
          deB.length === 0 ? "o filtro injectado isolou" : "");
      }
    } catch (erro) {
      naoMedido(id, "query graph / modulos", cenario, "filtro imposto pelo COM",
        `a sonda nao correu: ${(erro as Error).message}`);
    }
  }

  writeFileSync(`${SAIDA}/medusa-iso.json`, JSON.stringify(casos, null, 2));

  // --------------------------------------------------------------- AC-3
  await provaDeSobrevenda(container, logger);
}

/**
 * A prova de sobrevenda, pelos dois caminhos do Medusa.
 *
 * Arranja um `InventoryItem` com `stocked_quantity = 10` numa localizacao e
 * lanca `TENTATIVAS` reservas de 1 unidade em paralelo, duas vezes:
 *
 *   `modulo`   `createReservationItems` directo
 *   `locking`  o mesmo, dentro de `locking.execute([inventory_item_id], ...)`
 */
async function provaDeSobrevenda(container: ExecArgs["container"], logger: {
  info: (m: string) => void; error: (m: string) => void;
}) {
  // `as unknown as` e nao `as`: o `IInventoryService` declara tipos concretos
  // (`InventoryLevelDTO`) que nao se sobrepoem a forma generica que este guiao
  // usa, e o TypeScript recusa a conversao directa. O guiao so precisa de
  // chamar metodos e ler dois campos; declarar a forma minima e honesto, e a
  // conversao por `unknown` e a forma de o dizer ao compilador.
  const inventory = container.resolve(Modules.INVENTORY) as unknown as {
    createInventoryItems: (d: unknown) => Promise<{ id: string }[] | { id: string }>;
    createInventoryLevels: (d: unknown) => Promise<unknown>;
    createReservationItems: (d: unknown) => Promise<unknown>;
    retrieveInventoryLevel?: (...a: unknown[]) => Promise<unknown>;
    listInventoryLevels: (f?: unknown) => Promise<Record<string, unknown>[]>;
    listReservationItems: (f?: unknown) => Promise<Record<string, unknown>[]>;
  };
  const locking = container.resolve(Modules.LOCKING) as unknown as {
    execute: <T>(chaves: string[], trabalho: () => Promise<T>) => Promise<T>;
  };

  const resultados: Record<string, unknown> = {
    tentativas: TENTATIVAS,
    stock_inicial: STOCK,
    nota: "um processo so; ver o relatorio para o caso de varias instancias",
  };

  for (const modo of ["modulo", "locking"] as const) {
    try {
      const criado = await inventory.createInventoryItems({
        sku: `SPIKE-AC3-${modo}-${Date.now()}`,
      });
      const item = Array.isArray(criado) ? criado[0] : criado;
      const localizacao = `sloc_spike_${modo}`;
      await inventory.createInventoryLevels([
        {
          inventory_item_id: item.id,
          location_id: localizacao,
          stocked_quantity: STOCK,
        },
      ]);

      const reservar = () =>
        inventory.createReservationItems([
          {
            inventory_item_id: item.id,
            location_id: localizacao,
            quantity: 1,
            description: `spike ${modo}`,
          },
        ]);

      const tarefas = Array.from({ length: TENTATIVAS }, () =>
        (modo === "locking" ? locking.execute([item.id], reservar) : reservar())
          .then(() => "ok" as const)
          .catch((erro: Error) => `erro:${erro.message.slice(0, 80)}`),
      );
      const saidas = await Promise.all(tarefas);
      const sucessos = saidas.filter((s) => s === "ok").length;
      const recusas = saidas.length - sucessos;

      const niveis = await inventory.listInventoryLevels({
        inventory_item_id: item.id,
      });
      const nivel = niveis[0] ?? {};
      const reservada = Number(nivel.reserved_quantity ?? -1);
      const existente = Number(nivel.stocked_quantity ?? -1);

      // **Se não se conseguiu ler a quantidade, não há resultado.** Com
      // `reserved_quantity` ausente, `Number(undefined ?? -1)` dava `-1` e
      // `Math.max(0, -1 - 10)` dava `0` — ou seja «0 reservas acima do stock»
      // produzido por não se ter lido nada. Um `-1` é a ausência de medição, e
      // tem de aparecer como tal.
      if (reservada < 0 || existente < 0) {
        resultados[modo] = {
          erro:
            "nao se conseguiu ler `reserved_quantity`/`stocked_quantity` do "
            + "nivel de inventario apos a tempestade; sem esses numeros nao se "
            + "pode dizer nada sobre sobrevenda",
          sucessos,
          recusas,
          niveis_devolvidos: niveis.length,
        };
        logger.error(`spike AC-3 ${modo}: niveis ilegiveis`);
        continue;
      }
      // **A sobrevenda conta-se pelas reservas criadas, não pelo contador.**
      //
      // Medido a 2026-10-27, braço `modulo`: 105 reservas criadas sobre stock
      // 10, com `reserved_quantity` a dizer **10**. O contador não está só
      // errado — está errado *para o valor certo*, porque cada thread leu 9 e
      // escreveu 10. Ler a sobrevenda do contador dava «0 acima do stock» no
      // momento exacto em que houve 95 reservas a mais: o contador é a
      // vítima do *lost update*, não a testemunha.
      //
      // Contam-se então as linhas de `reservation_item` que existem de facto, e
      // reporta-se a divergência entre elas e o contador — que é a assinatura
      // do defeito.
      let linhasDeReserva = -1;
      try {
        const reservas = await inventory.listReservationItems({
          inventory_item_id: item.id,
        });
        linhasDeReserva = reservas.length;
      } catch (erro) {
        logger.error(
          `spike AC-3 ${modo}: nao se leu listReservationItems: `
          + `${(erro as Error).message}`,
        );
      }

      const acimaPorReservas = linhasDeReserva >= 0
        ? Math.max(0, linhasDeReserva - STOCK)
        : null;

      resultados[modo] = {
        sucessos,
        recusas,
        linhas_de_reserva_criadas: linhasDeReserva,
        reserved_quantity: reservada,
        stocked_quantity: existente,
        available_quantity: existente - reservada,
        // O numero que responde ao criterio.
        acima_do_stock: acimaPorReservas,
        // E o que denuncia o mecanismo.
        contador_divergente:
          linhasDeReserva >= 0 && linhasDeReserva !== reservada
            ? `${linhasDeReserva} reserva(s) existem e o contador diz `
              + `${reservada}: *lost update* no incremento de `
              + "`reserved_quantity`"
            : null,
      };
      logger.info(`spike AC-3 ${modo}: ${JSON.stringify(resultados[modo])}`);
    } catch (erro) {
      resultados[modo] = { erro: (erro as Error).message };
      logger.error(`spike AC-3 ${modo} falhou: ${(erro as Error).message}`);
    }
  }

  writeFileSync(`${SAIDA}/medusa-ac3.json`, JSON.stringify(resultados, null, 2));
}
