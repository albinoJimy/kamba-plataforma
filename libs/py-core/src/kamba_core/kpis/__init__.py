"""KPIs de onboarding, sinais de churn e tenants dormentes (KAM-117).

    limiares   o `config/kpis.yaml`, lido a falhar fechado
    churn      o *job* `churn-daily` e a reactivacao
    metricas   `onboarding_activation_minutes`, `churn_signal{sinal}`,
               `tenants_dormentes`

O desenho, as fontes de cada sinal e o que fica de fora estao em `docs/kpis.md`.
"""
