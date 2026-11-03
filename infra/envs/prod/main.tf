# infra/envs/prod — modulo de raiz do ambiente `prod` (KAM-075).
#
# LEIA-SE `env.yaml` ANTES DESTE FICHEIRO. Este `prod` arranca em
# `kamba_data_class=synthetic`, e nao por cautela: «sem D1 nao ha dados reais»
# (Carta §4.2), e o `tools/env_lint` recusa `real` sem referencia de decisao D1
# e sem `apd_ref`.
#
# NAO HA `resource`, `data` NEM `provider` NESTE FICHEIRO — regra do criterio 6,
# verificada pelo `env_lint` (`recurso-fora-da-costura`).

locals {
  env = yamldecode(file("${path.module}/env.yaml"))

  segredo_wireguard = "${local.env.segredos.projecto}/VPN_WIREGUARD_ADMIN"
}

module "host_base" {
  source = "../../modules/host-base"

  ambiente                        = local.env.ambiente
  ponto_de_montagem_nvme          = "/var/lib/kamba"
  referencia_do_segredo_wireguard = local.segredo_wireguard

  # Vazia: nao ha host. Em `prod` esta lista nunca sera a via normal de acesso —
  # o `acesso.modo` e `break-glass-auditado`, e quem o audita e o KAM-080.
  chaves_ssh_de_administracao = []
}

module "fornecedor" {
  source = "../../modules/provider-pendente"

  ambiente   = local.env.ambiente
  vcpu       = local.env.compute.vcpu
  memoria_gb = local.env.compute.memoria_gb

  # 200 GB e o minimo do perfil P0 (doc 09 §4.4: «NVMe >= 200 GB»). NAO E UM
  # ALVO: o doc 09 §8.2 avisa que com a base de dados acima de 40 GB o RTO de
  # 2 h deixa de ser seguro e passa a exigir replica de espera (P1). Crescer
  # este numero sem rever esse orcamento e esconder o problema no disco.
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

output "classe_de_dados" {
  description = <<-EOT
    O `kamba_data_class` com que este ambiente corre. Sai aqui para que um
    `plan` o mostre em voz alta: um `prod` a passar a `real` nao deve ser uma
    linha que ninguem viu.
  EOT
  value       = local.env.dados.classe
}
