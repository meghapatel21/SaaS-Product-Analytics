"""Chart styling matched to the Tableau workbook palette (tableau/SaaS Project.twb).

Two tiers of the same three hues: the exact Tableau tones fill large shapes (bars,
areas, heatmap cells); deeper companions draw thin lines and small markers, which the
pale fills cannot carry on a white page.
"""
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap

from src.utils.config import FIGURES_DIR

# Exact Tableau dashboard tones - fills
ACCENT_FILL = "#BCEAF8"
ALERT_FILL = "#F9D2C8"
NEUTRAL_FILL = "#E6E6E6"
PANEL_BG = "#F5F5F5"
INK = "#333333"

# Deeper companions of the same hues - lines, markers, edges
ACCENT = "#5FAECB"
ALERT = "#DE8A6E"
NEUTRAL = "#AEB6BD"
EDGE = "#FFFFFF"

PLAN_COLORS = {"Basic": "#BCEAF8", "Pro": "#5FAECB", "Enterprise": "#2E7FA0"}
SEQ_CMAP = LinearSegmentedColormap.from_list("ravenstack", ["#FFFFFF", "#BCEAF8", "#2E7FA0"])


def set_style() -> None:
    sns.set_theme(style="whitegrid", context="notebook")
    plt.rcParams.update({
        "figure.dpi": 110,
        "savefig.dpi": 150,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.titlecolor": INK,
        "axes.labelsize": 10,
        "axes.labelcolor": INK,
        "axes.edgecolor": "#D4D4D4",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "grid.color": NEUTRAL_FILL,
        "text.color": INK,
        "xtick.color": "#555555",
        "ytick.color": "#555555",
        "font.size": 10,
    })


def save_fig(fig, name: str) -> None:
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / f"{name}.png", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
