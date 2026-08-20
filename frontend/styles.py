"""
frontend/styles.py
------------------
Global CSS styles injected at app startup via st.markdown().
"""
import streamlit as st


GLOBAL_CSS = """
<style>
/* ── App header ── */
.app-title {
    font-size: 1.75rem; font-weight: 700; color: #1F4E79; margin-bottom: .1rem;
}
.app-sub {
    font-size: .88rem; color: #555; margin-bottom: .6rem;
}

/* ── Agent status badges ── */
.agent-badge {
    display: inline-block; padding: .18rem .65rem; border-radius: 12px;
    font-size: .8rem; font-weight: 600; margin: .12rem .06rem;
}
.b-idle { background: #e8f4fd; color: #1F4E79; border: 1px solid #1F4E79; }
.b-run  { background: #fff3cd; color: #856404; border: 1px solid #ffc107; }
.b-done { background: #d4edda; color: #155724; border: 1px solid #28a745; }
.b-err  { background: #f8d7da; color: #721c24; border: 1px solid #dc3545; }

/* ── Pipeline log terminal ── */
.plog {
    background: #0d1117; color: #c9d1d9;
    font-family: 'Courier New', monospace; font-size: .75rem;
    padding: .7rem 1rem; border-radius: 6px;
    max-height: 200px; overflow-y: auto;
    border: 1px solid #30363d; line-height: 1.5;
}
.le { color: #79c0ff; }
.lr { color: #56d364; }
.lg { color: #ffa657; }
.ls { color: #8b949e; }

/* ── Result banners ── */
.banner-yellow {
    background: #FFF3CD; border-left: 4px solid #FFC107;
    padding: .55rem .85rem; border-radius: 4px; margin: .35rem 0; font-size: .88rem;
}
.banner-red {
    background: #f8d7da; border-left: 4px solid #dc3545;
    padding: .55rem .85rem; border-radius: 4px; margin: .35rem 0; font-size: .88rem;
}
.banner-blue {
    background: #E8F4FD; border-left: 4px solid #1F4E79;
    padding: .55rem .85rem; border-radius: 4px; margin: .35rem 0; font-size: .88rem;
}
.banner-green {
    background: #d4edda; border-left: 4px solid #28a745;
    padding: .55rem .85rem; border-radius: 4px; margin: .35rem 0; font-size: .88rem;
}

/* ── Chat area ── */
.chat-section-header {
    font-size: 1.05rem; font-weight: 700; color: #1F4E79; margin-bottom: .3rem;
}

/* ── Hide Streamlit chrome ── */
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
</style>
"""


def inject_css() -> None:
    """Inject global CSS into the Streamlit app."""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
