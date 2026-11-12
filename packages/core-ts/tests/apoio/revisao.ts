/**
 * A montagem da fila de revisão para os ensaios (KAM-089): o serviço sobre os
 * duplos, com relógio controlado e todas as portas a registar o que recebem.
 */

import { randomBytes, randomUUID } from "node:crypto";

import { CifraAesGcm } from "../../src/kyc/index.ts";
import {
  AuditoriaEmMemoria,
  FilaDeRevisaoEmMemoria,
  LIMIARES_POR_OMISSAO,
  OnboardingsEmMemoria,
  ServicoDeRevisao,
  type CampoPessoal,
  type ChaveDeScreening,
  type Limiares,
  type MotivoDeAlerta,
  type MotivoPublico,
  type OnboardingDaRevisao,
  type OnboardingsDaRevisao,
  type Revisor,
  type TipoDeCaso,
  type ViaDoAviso,
  type Aviso,
} from "../../src/revisao/index.ts";

/** Uma sexta-feira, 10:00 em Luanda. */
export const SEXTA = new Date("2026-11-13T09:00:00Z");

export function revisor(o: Partial<Revisor> = {}): Revisor {
  return { id: randomUUID(), papeis: ["ts_revisor"], mfa: true, nifHmac: null, telefoneHmac: null, ...o };
}

export function montarRevisao(
  o: { agora?: Date; limiares?: Partial<Limiares>; inicioDaAmostragem?: Date | null; onboardings?: OnboardingsDaRevisao } = {},
) {
  let agora = o.agora ?? SEXTA;
  const relogio = () => agora;
  const onboardings = new OnboardingsEmMemoria();
  const repositorio = new FilaDeRevisaoEmMemoria((id) => {
    const c = onboardings.casos.get(id);
    return c === undefined ? null : (c.redeHmac ?? c.dispositivoHmac);
  }, relogio);
  const auditoria = new AuditoriaEmMemoria();
  const avisos: { onboardingId: string; via: ViaDoAviso; aviso: Aviso; motivoPublico: MotivoPublico | null }[] = [];
  const alertas: { motivo: MotivoDeAlerta; casoId: string; tipo: TipoDeCaso }[] = [];
  const humanas: { tenantId: string; chave: ChaveDeScreening; decisao: string; revisorId: string }[] = [];
  const dados = new Map<string, Partial<Record<CampoPessoal, string>>>();
  const urls: { revisor: string; onboardingId: string; verificacaoId: string }[] = [];
  const servico = new ServicoDeRevisao({
    repositorio,
    // Uma ponte para os onboardings de outro duplo (o do KYC) substitui estes:
    // o servico tem de ver os mesmos onboardings que as portas.
    onboardings: o.onboardings ?? onboardings,
    auditoria,
    aviso: { avisar: async (p) => void avisos.push({ ...p }) },
    alerta: (motivo, campos) => void alertas.push({ motivo, ...campos }),
    cifra: new CifraAesGcm(randomBytes(32)),
    dados: { ler: async (id, campo) => dados.get(id)?.[campo] ?? null },
    documentos: {
      async url(rev, onboardingId, verificacaoId, aud) {
        await aud.anotarAcesso({ revisor: rev, onboardingId, verificacaoId, em: relogio() });
        urls.push({ revisor: rev, onboardingId, verificacaoId });
        return `https://sto.invalid/${verificacaoId}?ttl=300`;
      },
    },
    screening: { gravar: async (p) => void humanas.push({ tenantId: p.tenantId, chave: p.chave, decisao: p.decisao, revisorId: p.revisorId }) },
    relogio,
    limiares: { ...LIMIARES_POR_OMISSAO, ...(o.limiares ?? {}) },
    inicioDaAmostragem: o.inicioDaAmostragem ?? null,
  });

  /** Um onboarding já depois do OTP, pronto para ter casos. */
  const onboarding = (c: Partial<OnboardingDaRevisao> = {}): OnboardingDaRevisao => {
    const o: OnboardingDaRevisao = {
      id: randomUUID(),
      tenantId: randomUUID(),
      fase: "em_revisao",
      redeHmac: randomBytes(32).toString("hex"),
      dispositivoHmac: null,
      nifHmac: randomBytes(32).toString("hex"),
      telefoneHmac: randomBytes(32).toString("hex"),
      ...c,
    };
    onboardings.casos.set(o.id, o);
    return o;
  };

  const abrir = (o: OnboardingDaRevisao, p: { tipo?: TipoDeCaso; prioridade?: number; motivoCodigo?: string; evidencias?: { tipo: string; ref: string }[] } = {}) =>
    servico.abrir({
      tipo: p.tipo ?? "kyc",
      tenantId: o.tenantId,
      onboardingId: o.id,
      motivoCodigo: p.motivoCodigo ?? "kyc_k1",
      motivoInterno: "marcas=nif_divergente;score=0",
      motivoPublico: "nao_foi_possivel_validar",
      evidencias: p.evidencias ?? [{ tipo: "kyc_check", ref: randomUUID() }],
      recomendacao: "investigar",
      prioridade: p.prioridade ?? 5,
    });

  return {
    servico,
    repositorio,
    onboardings,
    auditoria,
    avisos,
    alertas,
    humanas,
    dados,
    urls,
    onboarding,
    abrir,
    agora: () => agora,
    definir: (d: Date) => (agora = d),
    avancar: (ms: number) => (agora = new Date(agora.getTime() + ms)),
  };
}
