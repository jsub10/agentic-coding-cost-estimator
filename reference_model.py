"""Reference implementation of the corrected estimation model.
Generates the pinned figures. All twelve REVIEW.md defects addressed.
"""
from __future__ import annotations
import numpy as np

CLASSES = ["routine", "standard", "hard"]
COUNTS = {"routine": 80, "standard": 56, "hard": 24}
N_STORIES = sum(COUNTS.values())

W, W_INC, C = 150.0, 400.0, 3.0          # $/hr, $/hr, $/M tokens
I_HRS = 12.0                              # hours per escaped defect
A_MAX = 5
S_SWITCH = 0.25                           # hours per context switch
BATCH = 6                                 # touches per scheduled session
FALLBACK_HRS = 8.0                        # human execution of a capped story
RESTRUCTURE_FRAC = 0.05
ADJUDICATION_RATE = 0.40                  # share of stories raising a flagged question

K_FROZEN   = {"routine": 0.20e6, "standard": 1.30e6, "hard": 8.80e6}
K_UNFROZEN = {"routine": 0.25e6, "standard": 1.60e6, "hard": 11.0e6}

SCEN = {
 "A": dict(name="A. Execute only",   d=0.30, rho=0.70, m=0.30, f=0.00, S=3.0, R=2.5,
           frozen=False, p={"routine":0.85,"standard":0.50,"hard":0.28}, N={"routine":1,"standard":1,"hard":1},
           spec_h=0,  arch_h=40, adjud=False,
           app=dict(decide=0, oracle=0, cross=0, integ=0, repo=0)),
 "B": dict(name="B. + Decide",       d=0.24, rho=0.70, m=0.30, f=0.00, S=1.0, R=2.5,
           frozen=False, p={"routine":0.87,"standard":0.54,"hard":0.32}, N={"routine":1,"standard":1,"hard":1},
           spec_h=40, arch_h=40, adjud=False,
           app=dict(decide=600e6, oracle=0, cross=0, integ=0, repo=0)),
 "C": dict(name="C. + Deliver",      d=0.30, rho=0.05, m=0.06, f=0.85, S=3.0, R=1.5,
           frozen=True,  p={"routine":0.90,"standard":0.65,"hard":0.40}, N={"routine":1,"standard":2,"hard":2},
           spec_h=80, arch_h=40, adjud=True,
           app=dict(decide=0, oracle=592e6, cross=296e6, integ=120e6, repo=200e6)),
 "D": dict(name="D. All three",      d=0.24, rho=0.05, m=0.06, f=0.90, S=1.0, R=1.5,
           frozen=True,  p={"routine":0.92,"standard":0.70,"hard":0.45}, N={"routine":1,"standard":2,"hard":3},
           spec_h=80, arch_h=10, adjud=True,
           app=dict(decide=600e6, oracle=760e6, cross=368e6, integ=150e6, repo=250e6)),
 "D+": dict(name="D+. + quality",    d=0.24, rho=0.02, m=0.02, f=0.90, S=1.0, R=1.5,
           frozen=True,  p={"routine":0.92,"standard":0.70,"hard":0.45}, N={"routine":1,"standard":3,"hard":5},
           spec_h=80, arch_h=10, adjud=True,
           app=dict(decide=600e6, oracle=4460e6, cross=768e6, integ=200e6, repo=1850e6)),
}

# epistemic (parameter) uncertainty — drawn once per run
SIG_D, SIG_M, SIG_S, SIG_K = 0.20, 0.30, 0.25, 0.15
QREV_MEAN, QREV_SD = 0.35, 0.08
# aleatory (within-epic) — theta drawn once per run, loads on gate not generation
LAM_E, LAM_F, LAM_P = 0.55, 0.40, 0.15
P_CLUSTER, CLUSTER_MULT = 0.15, 3.0
SIG_TOK = 0.35


def e_from(d, rho, m, f, q):
    return d * (rho + (1 - rho) * m) * (f + (1 - f) * q)


def E_trunc(p, cap=A_MAX):
    q = 1 - p
    return sum(q ** k for k in range(cap))


def deterministic(sc):
    s = SCEN[sc]
    K = K_FROZEN if s["frozen"] else K_UNFROZEN
    gen = sum(COUNTS[c] * s["N"][c] * K[c] * E_trunc(s["p"][c]) for c in CLASSES)
    tokens = gen + sum(s["app"].values())
    e = e_from(s["d"], s["rho"], s["m"], s["f"], QREV_MEAN)
    # fallback: story falls back when fewer than min(2, N) implementations converge
    fb = 0.0
    for c in CLASSES:
        qf = (1 - s["p"][c]) ** A_MAX
        n = s["N"][c]
        if n == 1:
            pf = qf
        else:                       # P(fewer than 2 of n converge)
            pf = qf ** n + n * qf ** (n - 1) * (1 - qf)
        fb += COUNTS[c] * pf
    reviewed = (N_STORIES - fb) * (1 - s["f"])
    touches = N_STORIES + reviewed + (ADJUDICATION_RATE * N_STORIES if s["adjud"] else 0) + fb
    switch = touches / BATCH * S_SWITCH
    criteria = N_STORIES * s["S"]
    review = reviewed * s["R"]
    incid = e * N_STORIES * I_HRS
    fb_h = fb * FALLBACK_HRS
    restr = RESTRUCTURE_FRAC * (criteria + review + s["spec_h"] + s["arch_h"])
    non_inc = criteria + review + s["spec_h"] + s["arch_h"] + switch + fb_h + restr
    cost = tokens / 1e6 * C + non_inc * W + incid * W_INC
    return dict(tokens=tokens, e=e, fb=fb, reviewed=reviewed, criteria=criteria, review=review,
                incid=incid, switch=switch, fb_h=fb_h, restr=restr, spec=s["spec_h"], arch=s["arch_h"],
                hours=non_inc + incid, cost=cost, tok_cost=tokens / 1e6 * C)


def simulate(sc, iters=40000, seed=7, epistemic=True):
    rng = np.random.default_rng(seed)
    s = SCEN[sc]
    K = K_FROZEN if s["frozen"] else K_UNFROZEN
    one = np.ones(iters)

    if epistemic:
        d = s["d"] * rng.lognormal(-SIG_D**2/2, SIG_D, iters)
        m = np.clip(s["m"] * rng.lognormal(-SIG_M**2/2, SIG_M, iters), 0, 1)
        S = s["S"] * rng.lognormal(-SIG_S**2/2, SIG_S, iters)
        kscale = rng.lognormal(-SIG_K**2/2, SIG_K, iters)
        a = QREV_MEAN*((QREV_MEAN*(1-QREV_MEAN)/QREV_SD**2)-1)
        b = (1-QREV_MEAN)*((QREV_MEAN*(1-QREV_MEAN)/QREV_SD**2)-1)
        q = rng.beta(a, b, iters)
    else:
        d, m, S, q, kscale = s["d"]*one, s["m"]*one, s["S"]*one, QREV_MEAN*one, one

    theta = rng.standard_normal(iters)
    f_run = 1/(1+np.exp(-(np.log(s["f"]/(1-s["f"])) - LAM_F*theta))) if s["f"] > 0 else np.zeros(iters)
    e_base = e_from(d, s["rho"], m, f_run, q)
    # MEAN-PRESERVING scaling (defect S1-1)
    e_scale = np.exp(LAM_E*theta - LAM_E**2/2)
    off = (1 - P_CLUSTER*CLUSTER_MULT)/(1 - P_CLUSTER)
    clust = rng.random(iters) < P_CLUSTER
    e_scale = e_scale * np.where(clust, CLUSTER_MULT, off)
    e_run = np.clip(e_base*e_scale, 0, 1)

    tokens = np.zeros(iters); fb = np.zeros(iters)
    for c in CLASSES:
        n_draw = COUNTS[c]*s["N"][c]              # ONE DRAW PER IMPLEMENTATION (defect S1-2)
        p_story = 1/(1+np.exp(-(np.log(s["p"][c]/(1-s["p"][c])) + LAM_P*theta[:,None]
                               + 0.25*rng.standard_normal((iters, n_draw)))))
        A = np.minimum(rng.geometric(p_story), A_MAX)
        L = rng.lognormal(-SIG_TOK**2/2, SIG_TOK, (iters, n_draw))
        tokens += (A*L).sum(1) * K[c] * kscale
        # given A hit the cap, it failed outright with prob (1-p); P(cap)*P(fail|cap) = q^4 * q = q^5
        capped = (A == A_MAX) & (rng.random((iters, n_draw)) < (1 - p_story))
        capped = capped.reshape(iters, COUNTS[c], s["N"][c])
        need = min(2, s["N"][c])
        converged = s["N"][c] - capped.sum(2)
        fb += (converged < need).sum(1)
    tokens += sum(s["app"].values())

    reviewed = rng.binomial(np.maximum((N_STORIES-fb).astype(int), 0), 1-f_run)
    escaped = rng.binomial(N_STORIES, np.clip(e_run, 0, 1))
    touches = N_STORIES + reviewed + (ADJUDICATION_RATE*N_STORIES if s["adjud"] else 0) + fb
    switch = touches/BATCH*S_SWITCH
    criteria = N_STORIES*S
    review = reviewed*s["R"]
    incid = escaped*I_HRS
    fb_h = fb*FALLBACK_HRS
    restr = RESTRUCTURE_FRAC*(criteria+review+s["spec_h"]+s["arch_h"])
    non_inc = criteria+review+s["spec_h"]+s["arch_h"]+switch+fb_h+restr
    cost = tokens/1e6*C + non_inc*W + incid*W_INC
    return dict(cost=cost, tokens=tokens, e_run=e_run, escaped=escaped, hours=non_inc+incid)


if __name__ == "__main__":
    print(f"{'sc':<4}{'tokens':>9}{'tok$':>9}{'hours':>8}{'human$':>10}{'TOTAL':>11}{'share':>7}{'e':>7}{'fb':>6}")
    det = {}
    for sc in SCEN:
        r = deterministic(sc); det[sc] = r
        print(f"{sc:<4}{r['tokens']/1e9:8.2f}B{r['tok_cost']:9,.0f}{r['hours']:8.0f}"
              f"{r['cost']-r['tok_cost']:10,.0f}{r['cost']:11,.0f}{100*r['tok_cost']/r['cost']:6.1f}%"
              f"{100*r['e']:6.2f}%{r['fb']:6.1f}")
    print("\nsavings vs A:", {sc: f"{100*(1-det[sc]['cost']/det['A']['cost']):.0f}%" for sc in ["B","C","D","D+"]})
    print("\n--- Monte Carlo ---")
    for mode, ep in [("aleatory only", False), ("full (with parameter uncertainty)", True)]:
        print(f"\n{mode}")
        for sc in SCEN:
            r = simulate(sc, epistemic=ep)
            p50, p80, p95 = np.percentile(r["cost"], [50, 80, 95])
            print(f"  {sc:<4} P50 {p50:10,.0f}  P80 {p80:10,.0f}  P95 {p95:10,.0f}  P95/P50 {p95/p50:5.2f}"
                  f"   mean e {100*r['e_run'].mean():5.2f}% (derived {100*det[sc]['e']:5.2f}%)"
                  f"  tokenCV {100*r['tokens'].std()/r['tokens'].mean():4.1f}%")
