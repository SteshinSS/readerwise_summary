"""Reader Companion — a local, export-only intelligence layer over a Readwise Reader library.

See PRODUCT_PLAN.md for the full design. The package is organised around the plan's
feature set:

    parsing   (F1)  parse the library HTML + highlights CSV and join them
    layer1    (F2)  basic summary + tags + vibe, per document (gpt-5-mini)
    clustering(F4)  embed + cluster + name clusters
    profile   (F3)  build the temporal, evidence-backed interest profile
    layer3    (F5)  rich, personalised "smart summary", per document (gpt-5, low effort)
    render    (F6)  emit the single self-contained HTML report
    snapshot  (§8)  write the structured library snapshot the chat loads
    librarian (§8)  the agentic librarian chat — summaries in context + full text on demand

`generate.py` (at the repo root) wires the pipeline together into one batch run and writes the
chat snapshot; `chat.py` (at the repo root) is the terminal chat over that snapshot.
"""

__version__ = "1.0.0"
