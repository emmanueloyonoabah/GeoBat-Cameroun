"""GeoBat Cameroun — saisie, contrôle qualité et analyse des essais géotechniques
et de matériaux (béton, latérite, granulats).

Lancer en local :  streamlit run app.py
"""
from __future__ import annotations

import hashlib
import hmac
import html
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

st.set_page_config(
    page_title="GeoBat Cameroun",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data" / "essais.csv"
LOGO_FILE = BASE_DIR / "assets" / "logo.svg"
TZ = timezone(timedelta(hours=1))  # heure du Cameroun (WAT), pas d'heure d'été

STATUT_OK = "Conforme"
STATUT_WIP = "En cours d'analyse"
STATUT_NC = "Non conforme"
STATUTS = [STATUT_OK, STATUT_WIP, STATUT_NC]
STATUT_STYLE = {
    STATUT_OK: {"fg": "#15803D", "bg": "#DCFCE7", "dot": "🟢", "css": "ok"},
    STATUT_WIP: {"fg": "#B45309", "bg": "#FEF3C7", "dot": "🟠", "css": "wip"},
    STATUT_NC: {"fg": "#B91C1C", "bg": "#FEE2E2", "dot": "🔴", "css": "nc"},
}
NEUTRE = "#334155"

ROLE_TECH = "technicien"
ROLE_ING = "ingenieur"
ROLE_LABEL = {ROLE_TECH: "Technicien Labo", ROLE_ING: "Ingénieur / Chef de Projet"}

# Comptes de démonstration (mots de passe hachés PBKDF2-SHA256).
# En production : déclarer les comptes dans .streamlit/secrets.toml (section [users]),
# voir README.md — ces comptes de démo sont alors ignorés.
DEMO_USERS = {
    "tech": {
        "nom": "Technicien Labo (démo)",
        "role": ROLE_TECH,
        "salt": "a1f3c9d27b44e610",
        "hash": "33017ad626e0e14f9d5962a330a9bfc2eab32e4aa88ffb6d5e341c4d591a1e3e",
    },
    "ing": {
        "nom": "Ingénieur Chef de Projet (démo)",
        "role": ROLE_ING,
        "salt": "9be07d35c1a8f642",
        "hash": "5192a3275423f7e7fb17739e0cdb88c9b4fa83578743c3ccd829b12178f15c97",
    },
}
DEMO_IDENTIFIANTS = [("tech", "Labo@2025", ROLE_TECH), ("ing", "Chantier@2025", ROLE_ING)]
PBKDF2_ITER = 120_000

# ── Catalogue des essais ─────────────────────────────────────────────────────
# Seuils INDICATIFS : à aligner sur le CCTP / le marché du projet.
#   sens   : ">=" (valeur minimale exigée) ou "<=" (valeur maximale admise)
#   marge  : largeur de la zone « En cours d'analyse » au-delà de la cible
CATALOGUE = {
    "Compression béton à 28 jours": {
        "cle": "compression",
        "unite": "MPa",
        "sens": ">=",
        "marge": 4.0,
        "decimales": 1,
        "materiaux": ["Béton"],
        "contexte_label": "Classe de résistance",
        "contextes": {"C16/20": 20.0, "C20/25": 25.0, "C25/30": 30.0, "C30/37": 37.0, "C35/45": 45.0},
        "contexte_fmt": lambda k, v: f"{k} — fck,cube {v:g} MPa",
        "n_mesures": 3,
        "mesure_label": "Éprouvette",
        "max": 150.0,
        "pas": 0.1,
        "norme": "NF EN 12390-3 · NF EN 206/CN",
        "regle": "Moyenne des 3 éprouvettes ≥ fck,cube. Zone d'analyse : jusqu'à 4 MPa sous la cible "
                 "(critère individuel de la NF EN 206).",
    },
    "Proctor modifié — densité sèche max.": {
        "cle": "proctor",
        "unite": "t/m³",
        "sens": ">=",
        "marge": 0.05,
        "decimales": 2,
        "materiaux": ["Latérite / graveleux latéritique", "Grave non traitée", "Sable"],
        "contexte_label": "Utilisation prévue",
        "contextes": {"Remblai": 1.70, "Couche de forme": 1.80, "Couche de fondation": 1.90, "Couche de base": 2.00},
        "contexte_fmt": lambda k, v: f"{k} — γd ≥ {v:.2f} t/m³".replace(".", ","),
        "n_mesures": 1,
        "mesure_label": "γd max (OPM)",
        "max": 3.0,
        "pas": 0.01,
        "extra": {"label": "Teneur en eau optimale w_OPM (%) — facultatif", "max": 40.0},
        "norme": "NF P 94-093",
        "regle": "γd max ≥ seuil de l'utilisation prévue. Zone d'analyse : jusqu'à 0,05 t/m³ sous la cible.",
    },
    "CBR à 95 % de l'OPM": {
        "cle": "cbr",
        "unite": "%",
        "sens": ">=",
        "marge": 3.0,
        "decimales": 0,
        "materiaux": ["Latérite / graveleux latéritique", "Grave non traitée"],
        "contexte_label": "Utilisation prévue",
        "contextes": {"Remblai / plateforme": 15.0, "Couche de forme": 25.0, "Couche de fondation": 30.0, "Couche de base": 60.0},
        "contexte_fmt": lambda k, v: f"{k} — CBR ≥ {v:g} %",
        "n_mesures": 1,
        "mesure_label": "Indice CBR",
        "max": 250.0,
        "pas": 1.0,
        "norme": "NF P 94-078",
        "regle": "CBR ≥ seuil de l'utilisation prévue. Zone d'analyse : jusqu'à 3 points sous la cible.",
    },
    "Los Angeles (LA) — granulats": {
        "cle": "la",
        "unite": "%",
        "sens": "<=",
        "marge": 3.0,
        "decimales": 0,
        "materiaux": ["Granulats (gravillons)"],
        "contexte_label": "Utilisation prévue",
        "contextes": {"Béton hydraulique": 30.0, "Couche de chaussée": 35.0},
        "contexte_fmt": lambda k, v: f"{k} — LA ≤ {v:g} %",
        "n_mesures": 1,
        "mesure_label": "Coefficient LA",
        "max": 100.0,
        "pas": 1.0,
        "norme": "NF EN 1097-2",
        "regle": "Coefficient LA ≤ seuil (plus il est bas, plus le granulat est résistant). "
                 "Zone d'analyse : jusqu'à 3 points au-dessus de la cible.",
    },
}
PREFIXE_LOT = {
    "Béton": "BET",
    "Latérite / graveleux latéritique": "LAT",
    "Grave non traitée": "GNT",
    "Sable": "SAB",
    "Granulats (gravillons)": "GRA",
}

COLS = [
    "id_essai", "lot", "date_essai", "materiau", "provenance", "ouvrage", "type_essai", "contexte",
    "valeur_mesuree", "unite", "valeur_cible", "sens", "ecart", "statut_auto",
    "decision", "decision_par", "decision_date", "decision_motif",
    "detail_mesures", "observations", "technicien", "horodatage",
]
COLS_NUM = ["valeur_mesuree", "valeur_cible", "ecart"]

# ══════════════════════════════════════════════════════════════════════════════
# STYLE
# ══════════════════════════════════════════════════════════════════════════════
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root{
  --ink:#0F172A; --ink-2:#334155; --muted:#64748B; --line:#E2E5EA; --bg:#F7F6F3; --card:#FFFFFF;
  --ok:#15803D; --ok-bg:#DCFCE7; --nc:#B91C1C; --nc-bg:#FEE2E2; --wip:#B45309; --wip-bg:#FEF3C7;
}
html, body, .stApp, .stMarkdown, button, input, textarea, select { font-family:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif; }
.stApp { background:var(--bg); }
.block-container { padding-top:2.2rem; padding-bottom:4rem; max-width:1280px; }
#MainMenu, footer { visibility:hidden; }
[data-testid="stSidebar"] { border-right:1px solid var(--line); }
h1,h2,h3,h4 { color:var(--ink); letter-spacing:-0.01em; }

/* En-tête de page */
.gb-title { font-size:1.7rem; font-weight:700; color:var(--ink); letter-spacing:-0.02em; margin:0; line-height:1.2; }
.gb-sub { color:var(--muted); font-size:.95rem; margin:.3rem 0 1.4rem; }

/* Cartes KPI */
.gb-kpi { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:1rem 1.15rem;
  box-shadow:0 1px 2px rgba(15,23,42,.04); border-left:4px solid #CBD5E1; height:100%; }
.gb-kpi.ok { border-left-color:var(--ok); } .gb-kpi.nc { border-left-color:var(--nc); } .gb-kpi.wip { border-left-color:var(--wip); }
.gb-kpi-label { font-size:.72rem; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }
.gb-kpi-value { font-size:2rem; font-weight:700; color:var(--ink); line-height:1.15; margin-top:.25rem; letter-spacing:-0.02em; }
.gb-kpi.ok .gb-kpi-value { color:var(--ok); } .gb-kpi.nc .gb-kpi-value { color:var(--nc); } .gb-kpi.wip .gb-kpi-value { color:var(--wip); }
.gb-kpi-sub { font-size:.82rem; color:var(--muted); margin-top:.15rem; }

/* Badges de statut */
.gb-badge { display:inline-flex; align-items:center; gap:.4rem; padding:.22rem .7rem; border-radius:999px; font-weight:600; font-size:.8rem; }
.gb-badge::before { content:""; width:.5rem; height:.5rem; border-radius:50%; background:currentColor; }
.gb-badge.ok { color:var(--ok); background:var(--ok-bg); } .gb-badge.nc { color:var(--nc); background:var(--nc-bg); }
.gb-badge.wip { color:var(--wip); background:var(--wip-bg); }

/* Bandeaux d'alerte */
.gb-banner { display:flex; gap:.9rem; align-items:flex-start; padding:.9rem 1.15rem; border-radius:12px; border:1px solid; margin-bottom:.7rem; }
.gb-banner .gb-banner-icon { font-size:1.25rem; line-height:1.3; }
.gb-banner b { font-weight:700; } .gb-banner .gb-banner-text { font-size:.92rem; line-height:1.45; }
.gb-banner.nc { background:var(--nc-bg); border-color:#FCA5A5; color:#7F1D1D; }
.gb-banner.wip { background:var(--wip-bg); border-color:#FCD34D; color:#78350F; }
.gb-banner.ok { background:var(--ok-bg); border-color:#86EFAC; color:#14532D; }

/* Panneaux */
.gb-panel-title { font-weight:600; color:var(--ink); font-size:1rem; margin:0; }
.gb-panel-sub { color:var(--muted); font-size:.82rem; margin:.1rem 0 .4rem; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:14px; }
[data-testid="stForm"] { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:1.3rem 1.3rem .8rem; }

/* Cible réglementaire */
.gb-target { background:#EEF1F5; border:1px solid var(--line); border-radius:12px; padding:.85rem 1.1rem; margin:.4rem 0 1rem; display:flex; flex-wrap:wrap; gap:.4rem 2rem; align-items:baseline; }
.gb-target .lbl { font-size:.7rem; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }
.gb-target .val { font-size:1.15rem; font-weight:700; color:var(--ink); }
.gb-target .note { flex-basis:100%; font-size:.82rem; color:var(--ink-2); }

/* Résultat d'essai */
.gb-result { background:var(--card); border:1px solid var(--line); border-left:6px solid; border-radius:14px; padding:1.1rem 1.3rem; margin-bottom:1.1rem; box-shadow:0 1px 2px rgba(15,23,42,.04); }
.gb-result.ok { border-left-color:var(--ok); } .gb-result.nc { border-left-color:var(--nc); } .gb-result.wip { border-left-color:var(--wip); }
.gb-result-head { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:.5rem; margin-bottom:.8rem; }
.gb-result-meta { color:var(--muted); font-size:.82rem; }
.gb-result-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:1rem; }
.gb-result-grid .lbl { font-size:.7rem; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }
.gb-result-grid .val { font-size:1.45rem; font-weight:700; color:var(--ink); }
.gb-result-msg { margin-top:.8rem; font-size:.9rem; color:var(--ink-2); }

/* Connexion & marque */
.gb-login-brand { display:flex; align-items:center; gap:.8rem; margin-bottom:.4rem; }
.gb-logo { width:44px; height:44px; border-radius:12px; background:#0F172A; color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700; letter-spacing:.02em; }
.gb-login-name { font-size:1.5rem; font-weight:700; color:var(--ink); letter-spacing:-0.02em; line-height:1.1; }
.gb-login-tag { font-size:.75rem; color:var(--muted); text-transform:uppercase; letter-spacing:.1em; }
.gb-user { background:#fff; border:1px solid var(--line); border-radius:12px; padding:.7rem .9rem; margin-bottom:.6rem; }
.gb-user .n { font-weight:600; color:var(--ink); font-size:.9rem; } .gb-user .r { color:var(--muted); font-size:.78rem; }
"""


def injecter_css() -> None:
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# UTILITAIRES
# ══════════════════════════════════════════════════════════════════════════════
def esc(valeur) -> str:
    """Échappe toute valeur saisie avant insertion dans du HTML."""
    return html.escape(str(valeur), quote=True)


def _h(bloc: str) -> str:
    """Aplatit un bloc HTML (évite qu'une indentation soit prise pour du code Markdown)."""
    return "".join(ligne.strip() for ligne in bloc.splitlines())


def fr(valeur, decimales: int = 2) -> str:
    """Nombre au format français (virgule décimale)."""
    if valeur is None or (isinstance(valeur, float) and np.isnan(valeur)):
        return "—"
    return f"{valeur:.{decimales}f}".replace(".", ",")


def maintenant() -> datetime:
    return datetime.now(TZ)


def style_statut(statut: str) -> dict:
    return STATUT_STYLE.get(statut, {"fg": NEUTRE, "bg": "#E2E8F0", "dot": "⚪", "css": ""})


def badge(statut: str) -> str:
    return f'<span class="gb-badge {style_statut(statut)["css"]}">{esc(statut)}</span>'


def entete(titre: str, sous_titre: str = "") -> None:
    st.markdown(
        _h(f'<div class="gb-title">{esc(titre)}</div><div class="gb-sub">{esc(sous_titre)}</div>'),
        unsafe_allow_html=True,
    )


def carte_kpi(libelle: str, valeur: str, sous_texte: str = "", ton: str = "") -> str:
    return _h(
        f"""<div class="gb-kpi {ton}"><div class="gb-kpi-label">{esc(libelle)}</div>
        <div class="gb-kpi-value">{valeur}</div><div class="gb-kpi-sub">{esc(sous_texte)}</div></div>"""
    )


def panneau(titre: str, sous_titre: str = "") -> None:
    st.markdown(
        _h(f'<div class="gb-panel-title">{esc(titre)}</div><div class="gb-panel-sub">{esc(sous_titre)}</div>'),
        unsafe_allow_html=True,
    )


def flash(niveau: str, message: str) -> None:
    st.session_state["_flash"] = (niveau, message)


def afficher_flash() -> None:
    message = st.session_state.pop("_flash", None)
    if message:
        {"success": st.success, "error": st.error, "warning": st.warning}.get(message[0], st.info)(message[1])


def style_fig(fig: go.Figure, hauteur: int = 320) -> go.Figure:
    fig.update_layout(
        height=hauteur,
        margin=dict(l=8, r=8, t=24, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", size=12, color="#334155"),
        legend=dict(orientation="h", y=-0.2, x=0, title=None, traceorder="normal"),
    )
    fig.update_xaxes(gridcolor="#E8EAEE", zeroline=False, linecolor="#CBD5E1")
    fig.update_yaxes(gridcolor="#E8EAEE", zeroline=False)
    return fig


def afficher_fig(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


# ══════════════════════════════════════════════════════════════════════════════
# DONNÉES (CSV local)
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_resource
def _verrou() -> threading.Lock:
    """Verrou partagé entre les sessions pour sérialiser les écritures CSV."""
    return threading.Lock()


def charger_essais() -> pd.DataFrame:
    if DATA_FILE.exists():
        df = pd.read_csv(DATA_FILE, dtype=str, keep_default_na=False)
    else:
        df = pd.DataFrame(columns=COLS)
    for col in COLS:
        if col not in df.columns:
            df[col] = ""
    df = df[COLS].copy()
    for col in COLS_NUM:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date_essai"] = pd.to_datetime(df["date_essai"], errors="coerce")
    df["statut"] = np.where(df["decision"] != "", df["decision"], df["statut_auto"])
    return df


def _ecrire(df: pd.DataFrame) -> None:
    sortie = df[COLS].copy()
    sortie["date_essai"] = pd.to_datetime(sortie["date_essai"]).dt.strftime("%Y-%m-%d")
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    sortie.to_csv(tmp, index=False, encoding="utf-8")
    tmp.replace(DATA_FILE)  # remplacement atomique : jamais de fichier à moitié écrit


def ajouter_essais(lignes: list[dict]) -> list[str]:
    """Ajoute des essais, leur attribue un identifiant et renvoie la liste des identifiants."""
    with _verrou():
        df = charger_essais()
        numeros = pd.to_numeric(df["id_essai"].str.extract(r"(\d+)$")[0], errors="coerce")
        suivant = int(numeros.max()) + 1 if numeros.notna().any() else 1
        ids = []
        for ligne in lignes:
            ligne["id_essai"] = f"ESS-{suivant:05d}"
            ids.append(ligne["id_essai"])
            suivant += 1
        nouveau = pd.DataFrame(lignes).reindex(columns=COLS)
        _ecrire(nouveau if df.empty else pd.concat([df[COLS], nouveau], ignore_index=True))
    return ids


def appliquer_decision(id_essai: str, decision: str, motif: str, par: str) -> None:
    with _verrou():
        df = charger_essais()
        masque = df["id_essai"] == id_essai
        df.loc[masque, ["decision", "decision_par", "decision_motif"]] = [decision, par, motif.strip()]
        df.loc[masque, "decision_date"] = maintenant().strftime("%Y-%m-%d %H:%M:%S")
        _ecrire(df)


def prochain_lot(df: pd.DataFrame, materiau: str) -> str:
    prefixe = PREFIXE_LOT.get(materiau, "LOT")
    annee = maintenant().year
    motif = f"LOT-{prefixe}-{annee}-"
    existants = df.loc[df["lot"].str.startswith(motif), "lot"].str[len(motif):]
    numeros = pd.to_numeric(existants, errors="coerce").dropna()
    return f"{motif}{int(numeros.max()) + 1 if len(numeros) else 1:03d}"


# ══════════════════════════════════════════════════════════════════════════════
# RÈGLES MÉTIER
# ══════════════════════════════════════════════════════════════════════════════
def texte_critere(cfg: dict, cible: float) -> str:
    symbole = "≥" if cfg["sens"] == ">=" else "≤"
    return f"{symbole} {fr(cible, cfg['decimales'])} {cfg['unite']}"


def zone_analyse(cfg: dict, cible: float) -> str:
    d = max(cfg["decimales"], 2) if cfg["marge"] < 1 else cfg["decimales"]
    if cfg["sens"] == ">=":
        return f"{fr(cible - cfg['marge'], d)} à {fr(cible, d)} {cfg['unite']}"
    return f"{fr(cible, d)} à {fr(cible + cfg['marge'], d)} {cfg['unite']}"


def evaluer_essai(type_essai: str, contexte: str, mesures: list[float]) -> dict:
    """Compare le résultat à la valeur cible réglementaire et détermine le statut."""
    cfg = CATALOGUE[type_essai]
    cible = cfg["contextes"][contexte]
    valeur = round(float(np.mean(mesures)), cfg["decimales"])
    marge, eps = cfg["marge"], 1e-9
    if cfg["sens"] == ">=":
        statut = STATUT_OK if valeur >= cible - eps else STATUT_WIP if valeur >= cible - marge - eps else STATUT_NC
    else:
        statut = STATUT_OK if valeur <= cible + eps else STATUT_WIP if valeur <= cible + marge + eps else STATUT_NC
    dispersion = (max(mesures) - min(mesures)) / np.mean(mesures) * 100 if len(mesures) > 1 else 0.0
    detail = "; ".join(f"{m:.{cfg['decimales']}f}" for m in mesures) if len(mesures) > 1 else ""
    return {
        "valeur_mesuree": valeur,
        "valeur_cible": cible,
        "ecart": round(valeur - cible, 4),
        "statut_auto": statut,
        "detail_mesures": detail,
        "dispersion": float(dispersion),
    }


def construire_ligne(type_essai, contexte, mesures, *, lot, date_essai, materiau, provenance,
                     ouvrage, observations, technicien, horodatage, extra="") -> dict:
    cfg = CATALOGUE[type_essai]
    res = evaluer_essai(type_essai, contexte, mesures)
    detail = " | ".join(p for p in (res["detail_mesures"], extra) if p)
    return {
        "lot": lot.strip(), "date_essai": pd.Timestamp(date_essai), "materiau": materiau,
        "provenance": provenance.strip(), "ouvrage": ouvrage.strip(),
        "type_essai": type_essai, "contexte": contexte,
        "valeur_mesuree": res["valeur_mesuree"], "unite": cfg["unite"],
        "valeur_cible": res["valeur_cible"], "sens": cfg["sens"], "ecart": res["ecart"],
        "statut_auto": res["statut_auto"], "decision": "", "decision_par": "", "decision_date": "",
        "decision_motif": "", "detail_mesures": detail, "observations": observations.strip(),
        "technicien": technicien, "horodatage": horodatage.strftime("%Y-%m-%d %H:%M:%S"),
        "_dispersion": res["dispersion"],
    }


def resume_lots(df: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par lot ; le statut du lot est celui de son essai le plus défavorable."""
    if df.empty:
        return pd.DataFrame(columns=["lot", "materiau", "provenance", "ouvrage", "n_essais", "n_nc", "n_wip", "dernier_essai", "statut"])

    def pire(s: pd.Series) -> str:
        return STATUT_NC if (s == STATUT_NC).any() else STATUT_WIP if (s == STATUT_WIP).any() else STATUT_OK

    return (
        df.groupby("lot")
        .agg(
            materiau=("materiau", "first"), provenance=("provenance", "first"), ouvrage=("ouvrage", "first"),
            n_essais=("id_essai", "size"), n_nc=("statut", lambda s: int((s == STATUT_NC).sum())),
            n_wip=("statut", lambda s: int((s == STATUT_WIP).sum())),
            dernier_essai=("date_essai", "max"), statut=("statut", pire),
        )
        .reset_index()
        .sort_values("dernier_essai", ascending=False)
    )


def generer_donnees_demo(graine: int = 7) -> int:
    """Crée des essais fictifs réalistes pour découvrir l'application."""
    rng = np.random.default_rng(graine)
    aujourdhui = maintenant()
    # (matériau, provenance, ouvrage, [(essai, contextes possibles, décalage relatif, dispersion relative)], poids)
    scenarios = [
        ("Béton", "Centrale à béton A", "Immeuble R+4 – Bloc A",
         [("Compression béton à 28 jours", ["C25/30"], 0.17, 0.09)], 5),
        ("Béton", "Centrale à béton B", "Centre de santé de district",
         [("Compression béton à 28 jours", ["C20/25", "C25/30"], 0.03, 0.14)], 5),
        ("Latérite / graveleux latéritique", "Gîte d'emprunt GE-01", "Route Yaoundé–Bafoussam",
         [("Proctor modifié — densité sèche max.", ["Couche de fondation"], 0.05, 0.03),
          ("CBR à 95 % de l'OPM", ["Couche de fondation"], 0.25, 0.18)], 4),
        ("Latérite / graveleux latéritique", "Gîte d'emprunt GE-02", "Route Yaoundé–Bafoussam",
         [("Proctor modifié — densité sèche max.", ["Couche de forme"], 0.03, 0.035),
          ("CBR à 95 % de l'OPM", ["Couche de forme"], 0.12, 0.2)], 3),
        ("Latérite / graveleux latéritique", "Gîte d'emprunt GE-03", "Route Yaoundé–Bafoussam",
         [("Proctor modifié — densité sèche max.", ["Couche de fondation"], -0.01, 0.04),
          ("CBR à 95 % de l'OPM", ["Couche de fondation"], -0.14, 0.22)], 3),
        ("Granulats (gravillons)", "Carrière de granite C1", "Immeuble R+4 – Bloc A",
         [("Los Angeles (LA) — granulats", ["Béton hydraulique"], -0.12, 0.1)], 2),
        ("Granulats (gravillons)", "Carrière de granite C2", "Centre de santé de district",
         [("Los Angeles (LA) — granulats", ["Béton hydraulique"], 0.05, 0.1)], 2),
    ]
    poids = np.array([s[4] for s in scenarios], dtype=float)
    poids /= poids.sum()
    compteurs: dict[str, int] = {}
    lignes = []
    for _ in range(26):
        materiau, provenance, ouvrage, essais, _p = scenarios[rng.choice(len(scenarios), p=poids)]
        jour = (aujourdhui - timedelta(days=int(rng.integers(0, 180)))).date()
        horodatage = datetime.combine(jour, datetime.min.time(), tzinfo=TZ) + timedelta(hours=int(rng.integers(7, 17)), minutes=int(rng.integers(0, 60)))
        prefixe = PREFIXE_LOT[materiau]
        compteurs[prefixe] = compteurs.get(prefixe, 0) + 1
        lot = f"LOT-{prefixe}-{jour.year}-{compteurs[prefixe]:03d}"
        for type_essai, contextes, decalage, dispersion in essais:
            cfg = CATALOGUE[type_essai]
            contexte = str(rng.choice(contextes))
            cible = cfg["contextes"][contexte]
            moyenne = cible * (1 + rng.normal(decalage, dispersion))
            if cfg["n_mesures"] > 1:
                mesures = [max(moyenne * (1 + rng.normal(0, 0.03)), 0.1) for _ in range(cfg["n_mesures"])]
            else:
                mesures = [max(moyenne, 0.1)]
            lignes.append(construire_ligne(
                type_essai, contexte, [round(m, cfg["decimales"] + 1) for m in mesures],
                lot=lot, date_essai=jour, materiau=materiau, provenance=provenance, ouvrage=ouvrage,
                observations="Donnée de démonstration (simulée).", technicien="Démo (simulé)",
                horodatage=horodatage,
            ))
    for ligne in lignes:
        ligne.pop("_dispersion", None)
    return len(ajouter_essais(lignes))


def etat_vide(df: pd.DataFrame) -> bool:
    """Affiche l'état vide (avec option de démo) et renvoie True si aucune donnée."""
    if not df.empty:
        return False
    st.info("Aucun essai enregistré pour le moment. Les techniciens de laboratoire alimentent cette base depuis « Saisie laboratoire ».")
    if st.button("Charger des données de démonstration", type="primary"):
        n = generer_donnees_demo()
        flash("success", f"{n} essais fictifs ont été ajoutés (signalés « Démo (simulé) »).")
        st.rerun()
    return True


# ══════════════════════════════════════════════════════════════════════════════
# AUTHENTIFICATION
# ══════════════════════════════════════════════════════════════════════════════
def charger_utilisateurs() -> tuple[dict, bool]:
    """Renvoie (utilisateurs, mode_demo). Les secrets Streamlit ont priorité sur les comptes de démo."""
    try:
        if "users" in st.secrets:
            return {str(k).lower(): dict(v) for k, v in st.secrets["users"].items()}, False
    except Exception:
        pass
    return DEMO_USERS, True


def verifier_identifiants(identifiant: str, mot_de_passe: str) -> dict | None:
    utilisateurs, _ = charger_utilisateurs()
    compte = utilisateurs.get(identifiant.strip().lower())
    sel = str(compte.get("salt", "")) if compte else "inconnu"
    attendu = str(compte.get("hash", "")) if compte else "0" * 64
    calcule = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode(), sel.encode(), PBKDF2_ITER).hex()
    if compte and hmac.compare_digest(calcule, attendu) and compte.get("role") in ROLE_LABEL:
        return {"username": identifiant.strip().lower(), "nom": compte.get("nom", identifiant), "role": compte["role"]}
    return None


def utilisateur() -> dict:
    return st.session_state["user"]


def page_login() -> None:
    _, centre, _ = st.columns([1, 1.15, 1])
    with centre:
        st.markdown(
            _h("""<div style="height:3vh"></div><div class="gb-login-brand"><div class="gb-logo">GB</div>
            <div><div class="gb-login-name">GeoBat Cameroun</div>
            <div class="gb-login-tag">Laboratoire · Contrôle qualité BTP</div></div></div>"""),
            unsafe_allow_html=True,
        )
        st.markdown('<div class="gb-sub" style="margin-top:.6rem">Saisie, contrôle et analyse des essais géotechniques et de matériaux.</div>', unsafe_allow_html=True)
        with st.form("login"):
            identifiant = st.text_input("Identifiant")
            mot_de_passe = st.text_input("Mot de passe", type="password")
            valide = st.form_submit_button("Se connecter", type="primary", width="stretch")
        if valide:
            compte = verifier_identifiants(identifiant, mot_de_passe)
            if compte:
                st.session_state["user"] = compte
                st.rerun()
            st.error("Identifiant ou mot de passe incorrect.")
        _, mode_demo = charger_utilisateurs()
        if mode_demo:
            with st.expander("Comptes de démonstration"):
                st.caption("Mode démo : aucun compte n'est défini dans les secrets. Ne pas publier ainsi en production.")
                st.dataframe(
                    pd.DataFrame(DEMO_IDENTIFIANTS, columns=["Identifiant", "Mot de passe", "Rôle"]).assign(
                        Rôle=lambda d: d["Rôle"].map(ROLE_LABEL)),
                    hide_index=True, width="stretch",
                )


def barre_laterale() -> None:
    user = utilisateur()
    with st.sidebar:
        st.markdown(
            _h(f"""<div class="gb-user"><div class="n">{esc(user['nom'])}</div>
            <div class="r">{esc(ROLE_LABEL[user['role']])}</div></div>"""),
            unsafe_allow_html=True,
        )
        if st.button("Se déconnecter", width="stretch"):
            st.session_state.clear()
            st.rerun()
        st.caption("Heure du Cameroun (UTC+1) · " + maintenant().strftime("%d/%m/%Y %H:%M"))


# ══════════════════════════════════════════════════════════════════════════════
# COMPOSANTS D'AFFICHAGE
# ══════════════════════════════════════════════════════════════════════════════
def bandeau_alertes(df: pd.DataFrame) -> None:
    """Bandeau en haut de page dès qu'un lot non conforme (ou à instruire) est détecté."""
    if df.empty:
        return
    nc, wip = df[df["statut"] == STATUT_NC], df[df["statut"] == STATUT_WIP]
    if not nc.empty:
        lots = sorted(nc["lot"].unique())
        liste = ", ".join(lots[:4]) + (f" et {len(lots) - 4} autre(s)" if len(lots) > 4 else "")
        st.markdown(
            _h(f"""<div class="gb-banner nc"><div class="gb-banner-icon">⚠️</div><div class="gb-banner-text">
            <b>{len(lots)} lot(s) non conforme(s) détecté(s)</b> — {len(nc)} essai(s) hors tolérance, risque structurel potentiel.&nbsp;
            Lots concernés : {esc(liste)}. Isoler les lots et statuer depuis « Alertes &amp; décisions ».</div></div>"""),
            unsafe_allow_html=True,
        )
    if not wip.empty:
        st.markdown(
            _h(f"""<div class="gb-banner wip"><div class="gb-banner-icon">🔎</div><div class="gb-banner-text">
            <b>{len(wip)} essai(s) en cours d'analyse</b> — résultats proches du seuil : décision de l'ingénieur ou contre-essai requis.</div></div>"""),
            unsafe_allow_html=True,
        )
    if nc.empty and wip.empty:
        st.markdown(
            '<div class="gb-banner ok"><div class="gb-banner-icon">✅</div><div class="gb-banner-text"><b>Aucune non-conformité détectée</b> sur les essais enregistrés.</div></div>',
            unsafe_allow_html=True,
        )


def vue_essais(df: pd.DataFrame) -> pd.DataFrame:
    """Tableau lisible (colonnes françaises, statut coloré par pastille)."""
    return pd.DataFrame({
        "Statut": df["statut"].map(lambda s: f"{style_statut(s)['dot']} {s}"),
        "Date": df["date_essai"].dt.strftime("%d/%m/%Y"),
        "Lot": df["lot"], "Matériau": df["materiau"], "Provenance": df["provenance"], "Ouvrage": df["ouvrage"],
        "Essai": df["type_essai"], "Classe / usage": df["contexte"],
        "Mesuré": df["valeur_mesuree"], "Cible": df["valeur_cible"], "Unité": df["unite"],
        "Écart": df["ecart"], "Technicien": df["technicien"], "ID": df["id_essai"],
    })


def tableau(df: pd.DataFrame, hauteur: int | str = "auto") -> None:
    st.dataframe(
        vue_essais(df), hide_index=True, width="stretch", height=hauteur,
        column_config={
            "Mesuré": st.column_config.NumberColumn(format="%.2f"),
            "Cible": st.column_config.NumberColumn(format="%.2f"),
            "Écart": st.column_config.NumberColumn(format="%+.2f"),
        },
    )


def filtres(df: pd.DataFrame, prefixe: str) -> pd.DataFrame:
    c1, c2, c3 = st.columns([1, 1.3, 1.3])
    periode = c1.selectbox("Période", ["Tout l'historique", "30 derniers jours", "90 derniers jours", "6 derniers mois"], key=f"{prefixe}_periode")
    ouvrages = c2.multiselect("Ouvrage", sorted(df["ouvrage"].unique()), key=f"{prefixe}_ouvrage", placeholder="Tous les ouvrages")
    materiaux = c3.multiselect("Matériau", sorted(df["materiau"].unique()), key=f"{prefixe}_materiau", placeholder="Tous les matériaux")
    jours = {"30 derniers jours": 30, "90 derniers jours": 90, "6 derniers mois": 183}.get(periode)
    if jours:
        df = df[df["date_essai"] >= pd.Timestamp(maintenant().date()) - pd.Timedelta(days=jours)]
    if ouvrages:
        df = df[df["ouvrage"].isin(ouvrages)]
    if materiaux:
        df = df[df["materiau"].isin(materiaux)]
    return df


# ══════════════════════════════════════════════════════════════════════════════
# PAGES — TECHNICIEN
# ══════════════════════════════════════════════════════════════════════════════
def carte_cible(cfg: dict, contexte: str) -> None:
    cible = cfg["contextes"][contexte]
    st.markdown(
        _h(f"""<div class="gb-target">
        <div><div class="lbl">Valeur cible réglementaire</div><div class="val">{esc(texte_critere(cfg, cible))}</div></div>
        <div><div class="lbl">Zone « en cours d'analyse »</div><div class="val">{esc(zone_analyse(cfg, cible))}</div></div>
        <div><div class="lbl">Norme d'essai</div><div class="val">{esc(cfg['norme'])}</div></div>
        <div class="note">{esc(cfg['regle'])} Seuils indicatifs, à aligner sur le CCTP du marché.</div></div>"""),
        unsafe_allow_html=True,
    )


def carte_resultat(res: dict) -> None:
    css = style_statut(res["statut_auto"])["css"]
    messages = {
        STATUT_OK: "Essai conforme à la valeur cible.",
        STATUT_WIP: "Résultat dans la zone de tolérance : l'essai passe « en cours d'analyse ». "
                    "Un contre-essai est recommandé ; l'ingénieur statuera.",
        STATUT_NC: "Non-conformité détectée. Informer sans délai l'ingénieur / chef de projet et "
                   "isoler le lot en attendant sa décision.",
    }
    extra = ""
    if res["dispersion"] > 15:
        extra = f" ⚠ Dispersion élevée entre éprouvettes ({fr(res['dispersion'], 0)} %) : vérifier le prélèvement et l'écrasement."
    st.markdown(
        _h(f"""<div class="gb-result {css}"><div class="gb-result-head">{badge(res['statut_auto'])}
        <span class="gb-result-meta">{esc(res['id'])} · {esc(res['lot'])} · enregistré par {esc(res['technicien'])} le {esc(res['horodatage'])}</span></div>
        <div class="gb-result-grid">
        <div><div class="lbl">Valeur mesurée</div><div class="val">{esc(res['mesure'])}</div></div>
        <div><div class="lbl">Valeur cible</div><div class="val">{esc(res['critere'])}</div></div>
        <div><div class="lbl">Écart à la cible</div><div class="val">{esc(res['ecart'])}</div></div></div>
        <div class="gb-result-msg">{esc(messages[res['statut_auto']] + extra)}</div></div>"""),
        unsafe_allow_html=True,
    )


def page_saisie() -> None:
    user = utilisateur()
    df = charger_essais()
    entete("Saisie laboratoire", "Enregistrez un essai : la comparaison à la valeur cible et la traçabilité sont automatiques.")
    afficher_flash()
    dernier = st.session_state.pop("dernier_resultat", None)
    if dernier:
        carte_resultat(dernier)

    st.markdown("**1 · Type d'essai**")
    c1, c2, c3 = st.columns([1.3, 1, 1.2])
    type_essai = c1.selectbox("Type d'essai", list(CATALOGUE))
    cfg = CATALOGUE[type_essai]
    materiau = c2.selectbox("Matériau", cfg["materiaux"])
    contexte = c3.selectbox(cfg["contexte_label"], list(cfg["contextes"]),
                            format_func=lambda k: cfg["contexte_fmt"](k, cfg["contextes"][k]))
    carte_cible(cfg, contexte)

    st.markdown("**2 · Échantillon et mesures**")
    nonce = st.session_state.get("form_nonce", 0)
    with st.form(f"saisie_{cfg['cle']}_{PREFIXE_LOT[materiau]}_{nonce}"):
        a, b = st.columns(2)
        lot = a.text_input("Référence du lot", value=prochain_lot(df, materiau), help="Un lot peut regrouper plusieurs essais (ex. Proctor + CBR).")
        date_essai = b.date_input("Date de l'essai", value=maintenant().date(), max_value=maintenant().date(), format="DD/MM/YYYY")
        a, b = st.columns(2)
        provenance = a.text_input("Provenance / carrière", placeholder="Carrière, gîte d'emprunt ou centrale à béton")
        ouvrage = b.text_input("Ouvrage concerné", placeholder="Ex. Dalle R+2 – Bloc A, route, pont…")
        colonnes = st.columns(cfg["n_mesures"] if cfg["n_mesures"] > 1 else 2)
        mesures = []
        for i in range(cfg["n_mesures"]):
            etiquette = f"{cfg['mesure_label']} {i + 1} ({cfg['unite']})" if cfg["n_mesures"] > 1 else f"{cfg['mesure_label']} ({cfg['unite']})"
            mesures.append(colonnes[i].number_input(
                etiquette, min_value=0.0, max_value=cfg["max"], value=None, step=cfg["pas"],
                format=f"%.{max(cfg['decimales'], 1)}f", placeholder="0",
            ))
        w_opt = None
        if "extra" in cfg:
            w_opt = colonnes[1].number_input(cfg["extra"]["label"], min_value=0.0, max_value=cfg["extra"]["max"], value=None, step=0.1, format="%.1f", placeholder="0")
        observations = st.text_area("Observations", placeholder="Conditions d'essai, aspect de l'échantillon, écarts de procédure…", height=90)
        st.caption(f"Traçabilité : saisi par **{user['nom']}** — horodatage automatique à l'enregistrement.")
        envoye = st.form_submit_button("Enregistrer l'essai", type="primary")

    if not envoye:
        return
    erreurs = []
    if not lot.strip() or not provenance.strip() or not ouvrage.strip():
        erreurs.append("Renseignez la référence du lot, la provenance et l'ouvrage concerné.")
    if any(m is None or m <= 0 for m in mesures):
        erreurs.append("Renseignez toutes les mesures (valeurs strictement positives).")
    lot_existant = df[df["lot"] == lot.strip()]
    if not lot_existant.empty and (lot_existant["materiau"].iloc[0] != materiau or lot_existant["ouvrage"].iloc[0] != ouvrage.strip()):
        erreurs.append(f"Le lot {lot.strip()} existe déjà pour « {lot_existant['materiau'].iloc[0]} » / « {lot_existant['ouvrage'].iloc[0]} ». Utilisez une autre référence.")
    if erreurs:
        for e in erreurs:
            st.error(e)
        return

    horodatage = maintenant()
    ligne = construire_ligne(
        type_essai, contexte, [float(m) for m in mesures], lot=lot, date_essai=date_essai, materiau=materiau,
        provenance=provenance, ouvrage=ouvrage, observations=observations, technicien=user["nom"],
        horodatage=horodatage, extra=f"w_OPM = {w_opt:.1f} %" if w_opt else "",
    )
    dispersion = ligne.pop("_dispersion")
    id_essai = ajouter_essais([ligne])[0]
    st.session_state["dernier_resultat"] = {
        "id": id_essai, "lot": ligne["lot"], "technicien": user["nom"], "horodatage": horodatage.strftime("%d/%m/%Y %H:%M"),
        "statut_auto": ligne["statut_auto"], "dispersion": dispersion,
        "mesure": f"{fr(ligne['valeur_mesuree'], cfg['decimales'])} {cfg['unite']}",
        "critere": texte_critere(cfg, ligne["valeur_cible"]),
        "ecart": f"{ligne['ecart']:+.{max(cfg['decimales'], 1)}f} {cfg['unite']}".replace(".", ","),
    }
    st.session_state["form_nonce"] = nonce + 1
    st.rerun()


def page_mes_essais() -> None:
    user = utilisateur()
    df = charger_essais()
    entete("Mes essais", "Historique des essais que vous avez saisis, du plus récent au plus ancien.")
    mes = df[df["technicien"] == user["nom"]].sort_values("horodatage", ascending=False)
    if mes.empty:
        st.info("Vous n'avez saisi aucun essai pour le moment.")
        return
    aujourdhui = maintenant().strftime("%Y-%m-%d")
    k1, k2, k3 = st.columns(3)
    k1.markdown(carte_kpi("Saisis aujourd'hui", str((mes["horodatage"].str[:10] == aujourdhui).sum())), unsafe_allow_html=True)
    k2.markdown(carte_kpi("Total saisi", str(len(mes))), unsafe_allow_html=True)
    k3.markdown(carte_kpi("Non conformes", str((mes["statut"] == STATUT_NC).sum()), ton="nc"), unsafe_allow_html=True)
    st.write("")
    tableau(mes)


# ══════════════════════════════════════════════════════════════════════════════
# PAGES — INGÉNIEUR / CHEF DE PROJET
# ══════════════════════════════════════════════════════════════════════════════
def fig_statuts(f: pd.DataFrame, taux: float) -> go.Figure:
    comptes = f["statut"].value_counts().reindex(STATUTS, fill_value=0)
    fig = go.Figure(go.Pie(
        labels=comptes.index, values=comptes.values, hole=0.7, sort=False, direction="clockwise",
        marker=dict(colors=[STATUT_STYLE[s]["fg"] for s in comptes.index], line=dict(color="#FFFFFF", width=2)),
        textinfo="value", hovertemplate="%{label}: %{value} essai(s) (%{percent})<extra></extra>",
    ))
    fig.add_annotation(text=f"<b>{taux:.0f} %</b><br><span style='font-size:11px;color:#64748B'>conformes</span>",
                       showarrow=False, font=dict(size=24, color="#0F172A"))
    return style_fig(fig, 300)


def fig_provenances(f: pd.DataFrame) -> go.Figure:
    g = f.groupby(["provenance", "statut"]).size().unstack(fill_value=0).reindex(columns=STATUTS, fill_value=0)
    g["total"] = g.sum(axis=1)
    g = g.sort_values("total").tail(8)
    fig = go.Figure()
    for s in STATUTS:
        fig.add_bar(
            y=g.index, x=g[s] / g["total"] * 100, name=s, orientation="h", customdata=g[s],
            marker_color=STATUT_STYLE[s]["fg"], hovertemplate="%{y} — " + s + " : %{customdata} essai(s)<extra></extra>",
        )
    fig.update_layout(barmode="stack", bargap=0.35)
    fig.update_xaxes(range=[0, 100], ticksuffix=" %")
    return style_fig(fig, 300)


def fig_distribution(f: pd.DataFrame, type_essai: str) -> go.Figure | None:
    d = f[f["type_essai"] == type_essai].dropna(subset=["valeur_mesuree"])
    if d.empty:
        return None
    cfg = CATALOGUE.get(type_essai, {"decimales": 1, "unite": ""})
    lo, hi = float(d["valeur_mesuree"].min()), float(d["valeur_mesuree"].max())
    pas = (hi - lo) / 12 if hi > lo else 1.0
    fig = go.Figure()
    for s in STATUTS:
        x = d.loc[d["statut"] == s, "valeur_mesuree"]
        if len(x):
            fig.add_histogram(x=x, name=s, marker_color=STATUT_STYLE[s]["fg"], xbins=dict(start=lo, end=hi + pas, size=pas),
                              hovertemplate="%{x} " + cfg["unite"] + " : %{y} essai(s)<extra>" + s + "</extra>")
    fig.update_layout(barmode="stack", bargap=0.06)
    for cible in sorted(d["valeur_cible"].dropna().unique())[:4]:
        fig.add_vline(x=cible, line_dash="dash", line_color="#0F172A", line_width=1.5,
                      annotation_text=f"Cible {fr(cible, cfg['decimales'])}", annotation_position="top")
    fig.update_xaxes(title_text=f"Valeur mesurée ({cfg['unite']})")
    fig.update_yaxes(title_text="Nombre d'essais", dtick=1)
    style_fig(fig, 340)
    fig.update_layout(legend_y=-0.38)  # sous le titre de l'axe des x
    return fig


def fig_evolution(f: pd.DataFrame) -> go.Figure:
    m = f.dropna(subset=["date_essai"]).assign(mois=lambda d: d["date_essai"].dt.to_period("M").dt.to_timestamp())
    m = m.groupby("mois").agg(n=("id_essai", "size"), ok=("statut", lambda s: int((s == STATUT_OK).sum())))
    m["taux"] = m["ok"] / m["n"] * 100
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=m.index, y=m["n"], name="Essais réalisés", marker_color="#CBD5E1", secondary_y=True,
                text=m["n"], textposition="inside", insidetextanchor="start", textfont=dict(color="#475569"),
                hovertemplate="%{x|%b %Y} : %{y} essai(s)<extra></extra>")
    fig.add_scatter(x=m.index, y=m["taux"], name="Taux de conformité", mode="lines+markers",
                    line=dict(color="#0F172A", width=2.5), marker=dict(size=8), secondary_y=False,
                    hovertemplate="%{x|%b %Y} : %{y:.0f} %<extra></extra>")
    fig.update_yaxes(range=[0, 105], ticksuffix=" %", secondary_y=False)
    # barres cantonnées au bas du graphique pour ne pas masquer la courbe ; valeurs lisibles sur les barres
    fig.update_yaxes(showgrid=False, showticklabels=False, range=[0, max(int(m["n"].max()) * 2.6, 3)], secondary_y=True)
    fig.update_xaxes(tickformat="%b %Y")
    return style_fig(fig, 320)


def page_dashboard() -> None:
    df = charger_essais()
    entete("Tableau de bord qualité", "Conformité des matériaux reçus sur le chantier, en temps réel.")
    afficher_flash()
    if etat_vide(df):
        return
    bandeau_alertes(df)
    f = filtres(df, "dash")
    if f.empty:
        st.warning("Aucun essai ne correspond à ces filtres.")
        return

    n = len(f)
    n_ok, n_nc, n_wip = (int((f["statut"] == s).sum()) for s in (STATUT_OK, STATUT_NC, STATUT_WIP))
    taux = n_ok / n * 100
    ton_taux = "ok" if taux >= 90 else "wip" if taux >= 75 else "nc"
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(carte_kpi("Taux de conformité global", f"{taux:.0f} %", f"{n_ok} essai(s) conforme(s) sur {n}", ton_taux), unsafe_allow_html=True)
    k2.markdown(carte_kpi("Essais réalisés", str(n), f"{f['lot'].nunique()} lot(s) · {f['ouvrage'].nunique()} ouvrage(s)"), unsafe_allow_html=True)
    k3.markdown(carte_kpi("Non conformes", str(n_nc), f"{f.loc[f['statut'] == STATUT_NC, 'lot'].nunique()} lot(s) concerné(s)", "nc" if n_nc else ""), unsafe_allow_html=True)
    k4.markdown(carte_kpi("En cours d'analyse", str(n_wip), "décision de l'ingénieur requise" if n_wip else "rien à instruire", "wip" if n_wip else ""), unsafe_allow_html=True)
    st.caption("Taux de conformité = essais conformes ÷ essais réalisés. Un essai « en cours d'analyse » n'est pas encore compté comme conforme.")

    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        panneau("Répartition des résultats", "Nombre d'essais par statut")
        afficher_fig(fig_statuts(f, taux))
    with c2, st.container(border=True):
        panneau("Conformité par provenance", "Part des essais par statut, 8 provenances les plus testées")
        afficher_fig(fig_provenances(f))

    c3, c4 = st.columns(2)
    with c3, st.container(border=True):
        panneau("Distribution des résultats", "Valeurs mesurées, colorées par statut, avec la valeur cible en pointillés")
        types = sorted(f["type_essai"].unique())
        choix = st.selectbox("Type d'essai", types, key="dash_type", label_visibility="collapsed")
        fig = fig_distribution(f, choix)
        if fig:
            afficher_fig(fig)
    with c4, st.container(border=True):
        panneau("Évolution mensuelle", "Taux de conformité (courbe) et volume d'essais (barres)")
        afficher_fig(fig_evolution(f))

    with st.container(border=True):
        panneau("Derniers essais enregistrés")
        tableau(f.sort_values("horodatage", ascending=False).head(8))


def page_alertes() -> None:
    user = utilisateur()
    df = charger_essais()
    entete("Alertes & décisions", "Non-conformités à traiter et essais à instruire.")
    afficher_flash()
    if etat_vide(df):
        return
    bandeau_alertes(df)

    nc = df[df["statut"] == STATUT_NC].sort_values("date_essai", ascending=False)
    wip = df[df["statut"] == STATUT_WIP].sort_values("date_essai", ascending=False)

    with st.container(border=True):
        panneau("Non-conformités", f"{len(nc)} essai(s) hors tolérance — lots à isoler ou à rejeter")
        if nc.empty:
            st.success("Aucune non-conformité.")
        else:
            tableau(nc)
            st.caption("Actions usuelles : isoler le lot, notifier le fournisseur / la centrale, demander un contre-essai contradictoire, décider de la démolition ou du renforcement le cas échéant.")

    with st.container(border=True):
        panneau("Essais en cours d'analyse", f"{len(wip)} essai(s) dans la zone de tolérance — décision requise")
        if wip.empty:
            st.success("Aucun essai en attente de décision.")
            return
        tableau(wip)
        options = {
            f"{r.id_essai} · {r.lot} · {r.type_essai} : {fr(r.valeur_mesuree, 2)} {r.unite} (cible {fr(r.valeur_cible, 2)})": r.id_essai
            for r in wip.itertuples()
        }
        with st.form("decision", border=False):
            choix = st.selectbox("Essai à instruire", list(options))
            decision = st.radio("Décision", [STATUT_OK, STATUT_NC], horizontal=True,
                                format_func=lambda s: "Valider — conforme" if s == STATUT_OK else "Confirmer — non conforme")
            motif = st.text_area("Justification (obligatoire)", placeholder="Ex. contre-essai conforme sur éprouvettes témoins, tolérance admise par le CCTP…")
            valide = st.form_submit_button("Enregistrer la décision", type="primary")
        if valide:
            if len(motif.strip()) < 10:
                st.error("La justification est obligatoire (10 caractères minimum) pour garantir la traçabilité.")
            else:
                appliquer_decision(options[choix], decision, motif, user["nom"])
                flash("success", f"Décision enregistrée pour {options[choix]} : {decision}.")
                st.rerun()


def page_historique() -> None:
    df = charger_essais()
    entete("Historique par lot", "Tous les essais regroupés par lot de matériau.")
    afficher_flash()
    if etat_vide(df):
        return
    bandeau_alertes(df)
    lots = resume_lots(df)

    recherche = st.text_input("Rechercher", placeholder="Lot, ouvrage, provenance ou matériau…", key="hist_recherche")
    if recherche.strip():
        q = recherche.strip().lower()
        masque = lots[["lot", "ouvrage", "provenance", "materiau"]].apply(lambda col: col.str.lower().str.contains(q, regex=False)).any(axis=1)
        lots = lots[masque]
    with st.container(border=True):
        panneau(f"{len(lots)} lot(s)", "Le statut d'un lot est celui de son essai le plus défavorable")
        vue = pd.DataFrame({
            "Statut": lots["statut"].map(lambda s: f"{style_statut(s)['dot']} {s}"), "Lot": lots["lot"],
            "Matériau": lots["materiau"], "Provenance": lots["provenance"], "Ouvrage": lots["ouvrage"],
            "Essais": lots["n_essais"], "Non conformes": lots["n_nc"], "En analyse": lots["n_wip"],
            "Dernier essai": lots["dernier_essai"].dt.strftime("%d/%m/%Y"),
        })
        st.dataframe(vue, hide_index=True, width="stretch")

    choix = st.selectbox("Détail d'un lot", ["— Sélectionner un lot —"] + list(lots["lot"]))
    if choix.startswith("—"):
        return
    detail = df[df["lot"] == choix].sort_values("date_essai")
    entete_lot = lots[lots["lot"] == choix].iloc[0]
    with st.container(border=True):
        st.markdown(
            _h(f"""<div class="gb-result-head"><div class="gb-panel-title">{esc(choix)}</div>{badge(entete_lot['statut'])}</div>
            <div class="gb-panel-sub">{esc(entete_lot['materiau'])} · {esc(entete_lot['provenance'])} · {esc(entete_lot['ouvrage'])}</div>"""),
            unsafe_allow_html=True,
        )
        tableau(detail)
        for r in detail.itertuples():
            infos = [p for p in (r.detail_mesures, r.observations) if p]
            if r.decision:
                infos.append(f"Décision « {r.decision} » par {r.decision_par} le {r.decision_date} — {r.decision_motif}")
            if infos:
                st.caption(f"**{r.id_essai}** · " + " · ".join(infos))


def neutraliser_formules(df: pd.DataFrame) -> pd.DataFrame:
    """Préfixe les cellules texte qui commencent par = + - @ (injection de formules Excel)."""
    def sur(v):
        return "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
    sortie = df.copy()
    for col in sortie.columns:
        if not pd.api.types.is_numeric_dtype(sortie[col]):
            sortie[col] = sortie[col].map(sur)
    return sortie


def preparer_export(df: pd.DataFrame) -> pd.DataFrame:
    sens = df["sens"].map({">=": "Valeur ≥ cible", "<=": "Valeur ≤ cible"}).fillna("")
    out = pd.DataFrame({
        "ID essai": df["id_essai"], "Lot": df["lot"], "Date essai": df["date_essai"].dt.strftime("%d/%m/%Y"),
        "Matériau": df["materiau"], "Provenance / carrière": df["provenance"], "Ouvrage": df["ouvrage"],
        "Type d'essai": df["type_essai"], "Classe / usage": df["contexte"],
        "Valeur mesurée": df["valeur_mesuree"], "Unité": df["unite"], "Valeur cible": df["valeur_cible"],
        "Critère": sens, "Écart": df["ecart"], "Statut final": df["statut"], "Statut automatique": df["statut_auto"],
        "Décision ingénieur": df["decision"], "Décision par": df["decision_par"], "Décision le": df["decision_date"],
        "Justification": df["decision_motif"], "Détail des mesures": df["detail_mesures"],
        "Observations": df["observations"], "Technicien": df["technicien"], "Saisi le": df["horodatage"],
    })
    return neutraliser_formules(out)


def en_csv(df: pd.DataFrame, separateur: str) -> bytes:
    decimal = "," if separateur == ";" else "."
    return ("﻿" + df.to_csv(index=False, sep=separateur, decimal=decimal)).encode("utf-8")


def page_exports() -> None:
    user = utilisateur()
    df = charger_essais()
    entete("Rapports & exports", "Rapport de Contrôle Qualité au format CSV.")
    afficher_flash()
    if etat_vide(df):
        return
    f = filtres(df, "exp")
    if f.empty:
        st.warning("Aucun essai ne correspond à ces filtres.")
        return
    separateur = st.radio("Format du CSV", [";", ","], horizontal=True,
                          format_func=lambda s: "Point-virgule (Excel en français)" if s == ";" else "Virgule (international)")

    n = len(f)
    taux = (f["statut"] == STATUT_OK).sum() / n * 100
    k1, k2, k3 = st.columns(3)
    k1.markdown(carte_kpi("Essais dans le rapport", str(n), f"{f['lot'].nunique()} lot(s)"), unsafe_allow_html=True)
    k2.markdown(carte_kpi("Taux de conformité", f"{taux:.0f} %", "", "ok" if taux >= 90 else "wip" if taux >= 75 else "nc"), unsafe_allow_html=True)
    k3.markdown(carte_kpi("Non conformes", str((f["statut"] == STATUT_NC).sum()), "", "nc" if (f["statut"] == STATUT_NC).any() else ""), unsafe_allow_html=True)
    st.write("")

    horodatage = maintenant().strftime("%Y%m%d_%H%M")
    rapport = preparer_export(f.sort_values(["lot", "date_essai"]))
    lots = resume_lots(f)
    synthese = neutraliser_formules(pd.DataFrame({
        "Lot": lots["lot"], "Matériau": lots["materiau"], "Provenance / carrière": lots["provenance"], "Ouvrage": lots["ouvrage"],
        "Nombre d'essais": lots["n_essais"], "Non conformes": lots["n_nc"], "En cours d'analyse": lots["n_wip"],
        "Dernier essai": lots["dernier_essai"].dt.strftime("%d/%m/%Y"), "Statut du lot": lots["statut"],
    }))
    non_conformes = rapport[rapport["Statut final"] == STATUT_NC]

    b1, b2, b3 = st.columns(3)
    b1.download_button("Rapport de Contrôle Qualité (CSV)", en_csv(rapport, separateur), f"rapport_controle_qualite_{horodatage}.csv",
                       "text/csv", type="primary", width="stretch")
    b2.download_button("Synthèse par lot (CSV)", en_csv(synthese, separateur), f"synthese_lots_{horodatage}.csv",
                       "text/csv", width="stretch")
    b3.download_button(f"Non-conformités seules ({len(non_conformes)})", en_csv(non_conformes, separateur), f"non_conformites_{horodatage}.csv",
                       "text/csv", width="stretch", disabled=non_conformes.empty)
    st.caption(f"Rapport généré par {user['nom']} le {maintenant().strftime('%d/%m/%Y à %H:%M')} (heure du Cameroun).")

    with st.container(border=True):
        panneau("Aperçu du rapport", "Mêmes colonnes que le fichier téléchargé")
        st.dataframe(rapport, hide_index=True, width="stretch", height=360)


# ══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ══════════════════════════════════════════════════════════════════════════════
def pages_pour(role: str) -> list:
    if role == ROLE_TECH:
        return [
            st.Page(page_saisie, title="Saisie laboratoire", icon=":material/science:", url_path="saisie", default=True),
            st.Page(page_mes_essais, title="Mes essais", icon=":material/list_alt:", url_path="mes-essais"),
        ]
    return [
        st.Page(page_dashboard, title="Tableau de bord", icon=":material/dashboard:", url_path="tableau-de-bord", default=True),
        st.Page(page_alertes, title="Alertes & décisions", icon=":material/notification_important:", url_path="alertes"),
        st.Page(page_historique, title="Historique par lot", icon=":material/inventory_2:", url_path="historique"),
        st.Page(page_exports, title="Rapports & exports", icon=":material/download:", url_path="exports"),
    ]


def main() -> None:
    injecter_css()
    if "user" not in st.session_state:
        st.navigation([st.Page(page_login, title="Connexion", url_path="connexion")], position="hidden").run()
        return
    if LOGO_FILE.exists():
        st.logo(str(LOGO_FILE), size="large")
    navigation = st.navigation(pages_pour(utilisateur()["role"]))
    barre_laterale()
    navigation.run()


main()
