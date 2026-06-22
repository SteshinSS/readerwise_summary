"""Reader Companion — a local, export-only intelligence layer over a Readwise Reader library.

See PRODUCT_PLAN.md for the full design. The package is organised around the plan's
feature set:

    parsing   (F1)  parse the library HTML + highlights CSV and join them
    layer1    (F2)  basic summary + tags + vibe, per document (gpt-5-mini)
    clustering(F4)  embed + cluster + name clusters
    profile   (F3)  build the temporal, evidence-backed interest profile
    layer3    (F5)  rich, personalised "smart summary", per document (gpt-5, low effort)
    render    (F6)  emit the single self-contained HTML report

`generate.py` (at the repo root) wires these together into one batch run.
"""

__version__ = "1.0.0"
