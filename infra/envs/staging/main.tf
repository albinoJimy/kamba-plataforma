# infra/envs/staging — modulo de raiz do ambiente `staging` (KAM-075).
#
# NAO HA `resource`, `data` NEM `provider` NESTE FICHEIRO, e nao e minimalismo:
# e a regra do criterio 6, verificada pelo `tools/env_lint` com o achado
# `recurso-fora-da-costura`. Todo o recurso especifico de um fornecedor vive
# atras de `../../modules/provider-*/`. Ver `../../modules/README.md`.
#
# A CONFIGURACAO NAO SE REPETE AQUI: le-se de `env.yaml`, que e a mesma fonte
# que o `env_lint` compara com `infra/ENVIRONMENTS.md`. Um valor escrito duas
# vezes diverge; um valor lido de um ficheiro nao.

locals {
  env = yamldecode(file("${path.module}/env.yaml"))

  # A REFERENCIA de um segredo, derivada do projecto do ambiente. E a forma do
  # criterio 5, e deriva-se em vez de se escrever: tres projectos distintos dao
  # tres referencias distintas, pelo que «chaves Meta e do facilitador
  # distintas por ambiente» passa a ser consequencia e nao disciplina.
  #
  # O `env_lint` nao confia nesta derivacao: calcula as tres referencias dos
  # tres ambientes e exige que sejam diferentes duas a duas.
  segredo_wireguard = "${local.env.segredos.projecto}/VPN_WIREGUARD_ADMIN"
}

module "host_base" {
  source = "../../modules/host-base"

  ambiente                        = local.env.ambiente
  ponto_de_montagem_nvme          = "/var/lib/kamba"
  referencia_do_segredo_wireguard = local.segredo_wireguard

  # Vazia, e e o estado correcto: nao ha host e nao ha administrador com
  # acesso. Uma chave inventada aqui era pior do que nenhuma.
  chaves_ssh_de_administracao = []
}

module "fornecedor" {
  source = "../../modules/provider-pendente"

  ambiente   = local.env.ambiente
  vcpu       = local.env.compute.vcpu
  memoria_gb = local.env.compute.memoria_gb

  # 200 GB e o minimo do perfil P0 (doc 09 §4.4) e e o que `staging` leva: e o
  # ambiente de 4 vCPU/16 GB «a pedido», nao o de producao.
  disco_gb = 200

  cloud_init       = module.host_base.cloud_init
  dns_ttl_segundos = local.env.dns.ttl_segundos
  decisao_d1       = local.env.dados.decisao_d1
  etiquetas        = local.env.custo.etiquetas
}

output "forma" {
  description = "A forma de compute pedida. A unica saida que se le com a D1 aberta."
  value       = module.fornecedor.forma_pedida
}

output "quatro_coisas_do_criterio_2" {
  description = "O que o host tera ao fim do primeiro arranque. NAO observado num host."
  value       = module.host_base.quatro_coisas_do_criterio_2
}
