"""F6 — render the single, self-contained HTML report.

The whole dataset is serialised to JSON, embedded in the page, and rendered client-side by
a small vanilla-JS app (sort / filter / group / expand). No server, no external assets.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .models import Cluster, Document, Profile, Source
from .parsing import JoinResult


def _hl(h) -> dict[str, Any]:
    return {
        "text": h.text,
        "note": h.note,
        "tags": h.tags,
        "color": h.color,
        "date": h.highlighted_at.date().isoformat() if h.highlighted_at else None,
    }


def _doc_dict(doc: Document) -> dict[str, Any]:
    s = doc.summary
    sm = doc.smart
    return {
        "key": doc.key,
        "title": doc.title,
        "url": doc.reader_url,
        "bucket": doc.bucket,
        "cluster_id": doc.cluster_id,
        "tags": s.tags if s else [],
        "vibe": s.vibe if s else None,
        "content_type": s.content_type if s else None,
        "language": s.language if s else None,
        "reading_minutes": doc.reading_minutes,
        "effort": doc.effort,
        "word_count": doc.word_count,
        "basic_summary": s.summary if s else None,
        "smart": None if not sm else {
            "tldr": sm.tldr,
            "why_you": sm.why_you,
            "how_it_sits": sm.how_it_sits,
            "takeaways": sm.takeaways,
        },
        "matched": doc.matched,
        "highlights": [_hl(h) for h in doc.source.highlights] if doc.source else [],
        "error": doc.error,
    }


def build_report_data(join: JoinResult, clusters: list[Cluster], profile: Profile, *,
                      models: dict[str, str], mock: bool, title: str) -> dict[str, Any]:
    live = [d for d in join.documents if not d.is_stub]
    by_key = {d.key: d for d in live}

    cluster_dicts = []
    for c in clusters:
        present = [k for k in c.doc_keys if k in by_key]
        cluster_dicts.append({
            "id": c.id, "name": c.name, "description": c.description, "count": len(present),
        })

    n_highlights = sum(len(s.highlights) for s in join.sources)
    data = {
        "meta": {
            "title": title,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "mock": mock,
            "models": models,
            "n_docs": len(join.documents),
            "n_live": len(live),
            "n_clusters": len(clusters),
            "n_highlights": n_highlights,
            "n_matched": len(join.matched),
            "n_library_only": len(join.library_only),
            "n_highlights_only": len(join.highlights_only),
            "n_stubs": len(join.stubs),
            "skipped": [d.title for d in join.stubs],
            "failed": [{"title": d.title, "error": d.error} for d in live if d.error],
        },
        "clusters": cluster_dicts,
        "docs": [_doc_dict(d) for d in live],
        "unmatched_sources": [
            {
                "title": s.title,
                "author": s.author,
                "n_highlights": s.n_highlights,
                "latest": s.latest.date().isoformat() if s.latest else None,
                "highlights": [_hl(h) for h in s.highlights],
            }
            for s in join.highlights_only
        ],
    }
    return data


def render_html(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (
        _TEMPLATE
        .replace("__TITLE__", _escape(data["meta"]["title"]))
        .replace("__DATA_JSON__", payload)
    )


def write_report(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(data))


def _escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# --------------------------------------------------------------------------------------
# The page. __DATA_JSON__ / __TITLE__ are substituted above. CSS/JS use literal braces, so
# this is a plain string (never .format()-ed).
# --------------------------------------------------------------------------------------
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{
    --bg:#f7f7f5; --panel:#ffffff; --ink:#1d1d1f; --muted:#6b6b70; --line:#e6e6e2;
    --accent:#5b53d6; --accent-soft:#ecebfb; --chip:#f0f0ee; --link:#3a32b8;
    --good:#1f9d6b; --warn:#b9791f; --shadow:0 1px 2px rgba(0,0,0,.05),0 6px 18px rgba(0,0,0,.04);
    --radius:14px;
  }
  @media (prefers-color-scheme: dark){
    :root{
      --bg:#16161a; --panel:#1f1f25; --ink:#ececf1; --muted:#a0a0aa; --line:#2e2e36;
      --accent:#9b94ff; --accent-soft:#262346; --chip:#2a2a32; --link:#b3adff;
      --good:#56cc9b; --warn:#e0a955; --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25);
    }
  }
  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{
    margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }
  a{color:var(--link); text-decoration:none}
  a:hover{text-decoration:underline}
  .wrap{max-width:1080px; margin:0 auto; padding:32px 20px 80px}
  header.top h1{font-size:26px; margin:0 0 4px; letter-spacing:-.01em}
  header.top .sub{color:var(--muted); margin:0 0 16px}
  .stats{display:flex; flex-wrap:wrap; gap:8px; margin-bottom:8px}
  .stat{background:var(--panel); border:1px solid var(--line); border-radius:999px;
        padding:5px 12px; font-size:13px; box-shadow:var(--shadow)}
  .stat b{color:var(--ink)}
  .stat .lbl{color:var(--muted)}
  .banner{background:var(--accent-soft); color:var(--ink); border:1px solid var(--line);
           border-radius:10px; padding:8px 12px; font-size:13px; margin:12px 0}
  section.card{background:var(--panel); border:1px solid var(--line); border-radius:var(--radius);
               box-shadow:var(--shadow); padding:18px 20px; margin:18px 0}
  .card h2{font-size:14px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
           margin:0 0 14px}
  /* controls */
  .controls{position:sticky; top:0; z-index:5; background:var(--bg);
            padding:12px 0 10px; border-bottom:1px solid var(--line); margin-bottom:8px}
  .controls .row{display:flex; flex-wrap:wrap; gap:10px; align-items:center}
  .controls input[type=search], .controls select{
    font:inherit; color:var(--ink); background:var(--panel);
    border:1px solid var(--line); border-radius:9px; padding:8px 10px}
  .controls input[type=search]{flex:1; min-width:200px}
  .controls label.chk{font-size:13px; color:var(--muted); display:flex; align-items:center; gap:6px}
  .controls .count{margin-left:auto; color:var(--muted); font-size:13px}
  .btn{font:inherit; cursor:pointer; background:var(--panel); color:var(--ink);
       border:1px solid var(--line); border-radius:9px; padding:8px 10px}
  .btn:hover{border-color:var(--accent)}
  /* clusters + table */
  .cluster{margin:22px 0}
  .cluster .chead{display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:6px;
                  cursor:pointer; user-select:none}
  .cluster .chead:hover h3{color:var(--accent)}
  .ccaret{flex:0 0 auto; width:0; height:0; border-left:7px solid var(--muted);
          border-top:5px solid transparent; border-bottom:5px solid transparent;
          transition:transform .12s}
  .cluster.open .ccaret{transform:rotate(90deg)}
  .cluster .chead h3{margin:0; font-size:18px; letter-spacing:-.01em}
  .cluster .chead .cdesc{color:var(--muted); font-size:14px}
  .cluster .chead .cnum{color:var(--muted); font-size:13px; background:var(--chip);
                        border-radius:999px; padding:2px 9px}
  table{width:100%; border-collapse:collapse; background:var(--panel);
        border:1px solid var(--line); border-radius:var(--radius); overflow:hidden;
        box-shadow:var(--shadow)}
  thead th{font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted);
           text-align:left; padding:10px 14px; border-bottom:1px solid var(--line);
           cursor:pointer; user-select:none; white-space:nowrap}
  thead th .arrow{opacity:.5; font-size:10px}
  tbody tr.row{border-top:1px solid var(--line); cursor:pointer}
  tbody tr.row:hover{background:var(--accent-soft)}
  td{padding:11px 14px; vertical-align:top}
  td.title{font-weight:600; width:30%}
  td.title .ext{font-weight:400; font-size:12px; color:var(--muted); margin-left:6px}
  td.tldr{color:var(--ink)}
  td.meta-cell{white-space:nowrap; color:var(--muted); font-size:13px}
  .tags{display:flex; flex-wrap:wrap; gap:5px; margin-top:5px}
  .tag{font-size:11px; background:var(--chip); color:var(--muted); border-radius:999px;
       padding:2px 8px}
  .badge{display:inline-block; font-size:11px; border-radius:999px; padding:2px 8px;
         border:1px solid var(--line)}
  .badge.vibe{background:var(--accent-soft); color:var(--ink); border-color:transparent}
  .badge.hl{background:transparent; color:var(--good); border-color:var(--good)}
  .caret{display:inline-block; width:0;height:0;border-left:5px solid var(--muted);
         border-top:4px solid transparent;border-bottom:4px solid transparent;
         margin-right:8px; transition:transform .12s}
  tr.row.open .caret{transform:rotate(90deg)}
  tr.detail>td{background:var(--bg); border-top:1px dashed var(--line)}
  .detail-grid{display:grid; gap:14px; padding:6px 2px 10px}
  .detail h4{margin:0 0 4px; font-size:12px; text-transform:uppercase; letter-spacing:.05em;
             color:var(--muted)}
  .detail p{margin:0}
  .whyrow{display:grid; grid-template-columns:1fr 1fr; gap:14px}
  @media (max-width:640px){ .whyrow{grid-template-columns:1fr} td.title{width:auto} }
  .takeaways{margin:6px 0 0; padding-left:18px}
  .takeaways li{margin:3px 0}
  .hlquote{border-left:3px solid var(--accent); background:var(--panel); margin:6px 0;
           padding:6px 12px; border-radius:0 8px 8px 0; font-size:14px}
  .hlquote .note{display:block; color:var(--muted); font-size:13px; margin-top:3px}
  .metaline{font-size:13px; color:var(--muted)}
  .err{color:var(--warn); font-size:13px}
  footer{margin-top:40px; padding-top:18px; border-top:1px solid var(--line);
         color:var(--muted); font-size:13px}
  footer code{background:var(--chip); padding:1px 5px; border-radius:5px}
  details.foot summary{cursor:pointer; color:var(--ink)}
  .empty{color:var(--muted); padding:24px; text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1 id="h-title"></h1>
    <p class="sub" id="h-sub"></p>
    <div class="stats" id="h-stats"></div>
    <div class="banner" id="h-banner" style="display:none"></div>
  </header>

  <div class="controls">
    <div class="row">
      <input type="search" id="q" placeholder="Search titles, tags, summaries…" autocomplete="off">
      <select id="f-cluster"><option value="">All themes</option></select>
      <select id="f-tag"><option value="">All tags</option></select>
      <select id="f-effort"><option value="">Any length</option></select>
      <select id="f-vibe"><option value="">Any vibe</option></select>
    </div>
    <div class="row" style="margin-top:8px">
      <select id="sort">
        <option value="title">Sort: Title (A–Z)</option>
        <option value="time-asc">Sort: Reading time ↑</option>
        <option value="time-desc">Sort: Reading time ↓</option>
        <option value="hl-desc">Sort: Recently highlighted</option>
      </select>
      <label class="chk"><input type="checkbox" id="f-hl"> Highlighted only</label>
      <label class="chk"><input type="checkbox" id="f-group" checked> Group by theme</label>
      <button class="btn" id="expand-all">Expand all</button>
      <button class="btn" id="collapse-all">Collapse all</button>
      <span class="count" id="result-count"></span>
    </div>
  </div>

  <main id="results"></main>

  <section class="card" id="unmatched-card" style="display:none">
    <h2>Highlights with no matching document</h2>
    <p class="metaline">These sources are in your highlights export but couldn't be matched to a
    library document (different title, or not exported).</p>
    <div id="unmatched-body"></div>
  </section>

  <footer id="foot"></footer>
</div>

<script id="report-data" type="application/json">__DATA_JSON__</script>
<script>
(function(){
  "use strict";
  var DATA = JSON.parse(document.getElementById("report-data").textContent);
  var DOCS = DATA.docs, META = DATA.meta;
  var clusterById = {}; DATA.clusters.forEach(function(c){ clusterById[c.id]=c; });

  // ---- helpers ----
  function el(tag, cls, text){ var e=document.createElement(tag); if(cls)e.className=cls;
    if(text!=null)e.textContent=text; return e; }
  function latestHl(d){ var t=0; (d.highlights||[]).forEach(function(h){
    if(h.date){ var v=Date.parse(h.date)||0; if(v>t)t=v; } }); return t; }

  // ---- header ----
  document.getElementById("h-title").textContent = META.title;
  document.getElementById("h-sub").textContent =
    "Generated " + META.generated + " · export-only snapshot of your Readwise Reader library";
  var stats = document.getElementById("h-stats");
  function stat(lbl, val){ var s=el("span","stat"); s.appendChild(el("b",null,String(val)));
    s.appendChild(document.createTextNode(" ")); s.appendChild(el("span","lbl",lbl)); stats.appendChild(s); }
  stat("documents", META.n_live);
  stat("themes", META.n_clusters);
  stat("highlights", META.n_highlights);
  stat("with highlights", META.n_matched);
  if(META.n_highlights_only) stat("unmatched sources", META.n_highlights_only);
  if(META.n_stubs) stat("skipped (failed export)", META.n_stubs);

  var banner = document.getElementById("h-banner");
  var notes = [];
  if(META.mock) notes.push("⚠︎ MOCK MODE — summaries/embeddings are placeholders, not real model output. Re-run without --mock for the real report.");
  if(META.failed && META.failed.length) notes.push(META.failed.length + " document(s) failed an LLM stage (see footer).");
  if(notes.length){ banner.style.display="block"; banner.textContent = notes.join("  "); }

  // ---- populate filters ----
  (function(){
    var fc=document.getElementById("f-cluster");
    DATA.clusters.slice().sort(function(a,b){return b.count-a.count;}).forEach(function(c){
      var o=el("option",null,c.name+" ("+c.count+")"); o.value=String(c.id); fc.appendChild(o);
    });
    var tags={}; DOCS.forEach(function(d){(d.tags||[]).forEach(function(t){tags[t]=(tags[t]||0)+1;});});
    var ft=document.getElementById("f-tag");
    Object.keys(tags).sort(function(a,b){return tags[b]-tags[a]||a.localeCompare(b);})
      .forEach(function(t){ var o=el("option",null,t+" ("+tags[t]+")"); o.value=t; ft.appendChild(o); });
    var efOrder=["Quick","Medium","Long","Epic"], efs={};
    DOCS.forEach(function(d){ if(d.effort)efs[d.effort]=true; });
    var fe=document.getElementById("f-effort");
    efOrder.forEach(function(e){ if(efs[e]){var o=el("option",null,e);o.value=e;fe.appendChild(o);} });
    var vibes={}; DOCS.forEach(function(d){ if(d.vibe)vibes[d.vibe]=true; });
    var fv=document.getElementById("f-vibe");
    Object.keys(vibes).sort().forEach(function(v){var o=el("option",null,v);o.value=v;fv.appendChild(o);});
  })();

  // ---- state ----
  var state={q:"",cluster:"",tag:"",effort:"",vibe:"",hlOnly:false,group:true,sort:"title"};
  var openKeys={};       // expanded article-detail rows
  var openClusters={};   // expanded theme groups (folded by default)

  function matches(d){
    if(state.cluster!=="" && String(d.cluster_id)!==state.cluster) return false;
    if(state.tag && (d.tags||[]).indexOf(state.tag)<0) return false;
    if(state.effort && d.effort!==state.effort) return false;
    if(state.vibe && d.vibe!==state.vibe) return false;
    if(state.hlOnly && !d.matched) return false;
    if(state.q){
      var hay=(d.title+" "+(d.tags||[]).join(" ")+" "+(d.basic_summary||"")+" "+
        (d.smart?(d.smart.tldr+" "+d.smart.why_you+" "+d.smart.how_it_sits):"")).toLowerCase();
      if(hay.indexOf(state.q)<0) return false;
    }
    return true;
  }
  function sortDocs(list){
    var s=state.sort, a=list.slice();
    a.sort(function(x,y){
      if(s==="time-asc") return x.reading_minutes-y.reading_minutes || x.title.localeCompare(y.title);
      if(s==="time-desc") return y.reading_minutes-x.reading_minutes || x.title.localeCompare(y.title);
      if(s==="hl-desc") return latestHl(y)-latestHl(x) || x.title.localeCompare(y.title);
      return x.title.localeCompare(y.title);
    });
    return a;
  }

  function tagsEl(d){
    var w=el("div","tags");
    (d.tags||[]).forEach(function(t){ w.appendChild(el("span","tag",t)); });
    return w;
  }
  function detailRow(d, cols){
    var tr=el("tr","detail"); var td=el("td"); td.colSpan=cols;
    var g=el("div","detail-grid");
    if(d.smart){
      var why=el("div","whyrow");
      var b1=el("div","detail"); b1.appendChild(el("h4",null,"Why you"));
      b1.appendChild(el("p",null,d.smart.why_you)); why.appendChild(b1);
      var b2=el("div","detail"); b2.appendChild(el("h4",null,"How it sits in your library"));
      b2.appendChild(el("p",null,d.smart.how_it_sits)); why.appendChild(b2);
      g.appendChild(why);
      if(d.smart.takeaways && d.smart.takeaways.length){
        var tk=el("div","detail"); tk.appendChild(el("h4",null,"What you'll get"));
        var ul=el("ul","takeaways");
        d.smart.takeaways.forEach(function(t){ ul.appendChild(el("li",null,t)); });
        tk.appendChild(ul); g.appendChild(tk);
      }
    }
    if(d.basic_summary){
      var bs=el("div","detail"); bs.appendChild(el("h4",null,"Basic summary"));
      bs.appendChild(el("p",null,d.basic_summary)); g.appendChild(bs);
    }
    if(d.highlights && d.highlights.length){
      var hb=el("div","detail"); hb.appendChild(el("h4",null,"Your highlights ("+d.highlights.length+")"));
      d.highlights.forEach(function(h){
        var q=el("div","hlquote"); q.appendChild(document.createTextNode("“"+h.text+"”"));
        if(h.note) q.appendChild(el("span","note","note: "+h.note));
        hb.appendChild(q);
      });
      g.appendChild(hb);
    }
    var meta=el("div","detail");
    var parts=[];
    parts.push(d.bucket);
    if(d.content_type)parts.push(d.content_type);
    if(d.language)parts.push(d.language);
    parts.push(d.word_count+" words · "+d.reading_minutes+" min ("+d.effort+")");
    var ml=el("p","metaline",parts.join(" · "));
    meta.appendChild(ml);
    if(d.url){ var a=el("a",null,"Open in Readwise Reader →"); a.href=d.url; a.target="_blank";
      a.rel="noopener"; var p=el("p"); p.appendChild(a); meta.appendChild(p); }
    if(d.error){ meta.appendChild(el("p","err","⚠︎ "+d.error)); }
    g.appendChild(meta);
    td.appendChild(g); tr.appendChild(td); return tr;
  }
  function buildTable(list){
    var table=el("table");
    var thead=el("thead"); var htr=el("tr");
    [["Title","title"],["Tags",""],["Length · Vibe",""],["TL;DR","tldr"]].forEach(function(h){
      var th=el("th",null,h[0]); htr.appendChild(th);
    });
    thead.appendChild(htr); table.appendChild(thead);
    var tb=el("tbody");
    list.forEach(function(d){
      var tr=el("tr","row"); if(openKeys[d.key]) tr.classList.add("open");
      // title
      var tdT=el("td","title");
      var caret=el("span","caret"); tdT.appendChild(caret);
      tdT.appendChild(document.createTextNode(d.title));
      if(d.matched){ var bd=el("span","badge hl","★ highlighted"); bd.style.marginLeft="8px"; tdT.appendChild(bd); }
      tr.appendChild(tdT);
      // tags
      var tdTags=el("td"); tdTags.appendChild(tagsEl(d)); tr.appendChild(tdTags);
      // length+vibe
      var tdM=el("td","meta-cell");
      tdM.appendChild(document.createTextNode(d.reading_minutes+" min"));
      tdM.appendChild(el("div",null,""));
      if(d.vibe){ var vb=el("span","badge vibe",d.vibe); tdM.appendChild(vb); }
      tr.appendChild(tdM);
      // tldr
      var tdL=el("td","tldr", d.smart? d.smart.tldr : (d.basic_summary||"—"));
      tr.appendChild(tdL);

      var det=detailRow(d,4); det.style.display=openKeys[d.key]?"":"none";
      tr.addEventListener("click", function(ev){
        if(ev.target.tagName==="A") return;
        var isOpen=tr.classList.toggle("open");
        openKeys[d.key]=isOpen; det.style.display=isOpen?"":"none";
      });
      tb.appendChild(tr); tb.appendChild(det);
    });
    table.appendChild(tb);
    return table;
  }

  function render(){
    var root=document.getElementById("results"); root.textContent="";
    var visible=DOCS.filter(matches);
    document.getElementById("result-count").textContent=
      visible.length+" of "+DOCS.length+" shown";
    if(!visible.length){ root.appendChild(el("div","empty","No documents match your filters.")); return; }

    if(state.group){
      var groups={};
      visible.forEach(function(d){ var k=(d.cluster_id==null?"none":String(d.cluster_id));
        (groups[k]=groups[k]||[]).push(d); });
      var order=DATA.clusters.slice().sort(function(a,b){return b.count-a.count;})
        .map(function(c){return String(c.id);});
      if(groups["none"]) order.push("none");
      // While a search/filter is active, force groups open so matches are never hidden.
      var filterActive=!!(state.q||state.cluster||state.tag||state.effort||state.vibe||state.hlOnly);
      order.forEach(function(k){
        if(!groups[k]) return;
        var c=clusterById[k];
        var sec=el("div","cluster");
        var head=el("div","chead");
        head.appendChild(el("span","ccaret"));
        head.appendChild(el("h3",null, c? c.name : "Uncategorised"));
        head.appendChild(el("span","cnum",groups[k].length+" shown"));
        if(c && c.description) head.appendChild(el("span","cdesc",c.description));
        var body=el("div","cbody");
        body.appendChild(buildTable(sortDocs(groups[k])));
        var open=filterActive||!!openClusters[k];
        if(open) sec.classList.add("open"); else body.style.display="none";
        head.addEventListener("click", function(){
          var nowOpen=!sec.classList.contains("open");
          sec.classList.toggle("open", nowOpen);
          body.style.display=nowOpen?"":"none";
          openClusters[k]=nowOpen;
        });
        sec.appendChild(head);
        sec.appendChild(body);
        root.appendChild(sec);
      });
    } else {
      root.appendChild(buildTable(sortDocs(visible)));
    }
  }

  // ---- wire controls ----
  function bind(id,evt,fn){ document.getElementById(id).addEventListener(evt,fn); }
  bind("q","input",function(e){ state.q=e.target.value.trim().toLowerCase(); render(); });
  bind("f-cluster","change",function(e){ state.cluster=e.target.value; render(); });
  bind("f-tag","change",function(e){ state.tag=e.target.value; render(); });
  bind("f-effort","change",function(e){ state.effort=e.target.value; render(); });
  bind("f-vibe","change",function(e){ state.vibe=e.target.value; render(); });
  bind("sort","change",function(e){ state.sort=e.target.value; render(); });
  bind("f-hl","change",function(e){ state.hlOnly=e.target.checked; render(); });
  bind("f-group","change",function(e){ state.group=e.target.checked; render(); });
  bind("expand-all","click",function(){
    DOCS.forEach(function(d){openKeys[d.key]=true;});
    DATA.clusters.forEach(function(c){openClusters[String(c.id)]=true;}); openClusters["none"]=true;
    render();
  });
  bind("collapse-all","click",function(){ openKeys={}; openClusters={}; render(); });

  // ---- unmatched sources ----
  (function(){
    var U=DATA.unmatched_sources||[];
    if(!U.length) return;
    document.getElementById("unmatched-card").style.display="";
    var body=document.getElementById("unmatched-body");
    U.forEach(function(s){
      var d=el("details");
      var sum=el("summary");
      sum.appendChild(el("b",null,s.title));
      var meta=" · "+s.n_highlights+" highlight(s)"+(s.latest?(" · latest "+s.latest):"")+
        (s.author?(" · "+s.author):"");
      sum.appendChild(el("span","metaline",meta));
      d.appendChild(sum);
      (s.highlights||[]).forEach(function(h){
        var q=el("div","hlquote"); q.appendChild(document.createTextNode("“"+h.text+"”"));
        if(h.note) q.appendChild(el("span","note","note: "+h.note));
        d.appendChild(q);
      });
      body.appendChild(d);
    });
  })();

  // ---- footer ----
  (function(){
    var f=document.getElementById("foot");
    var m=META.models||{};
    var p=el("p");
    p.innerHTML="Built by <b>Reader Companion</b> from an export-only snapshot. "+
      "Layer 1 (basic summary + tags): <code>"+(m.layer1||"?")+"</code> · "+
      "Embeddings: <code>"+(m.embed||"?")+"</code> · "+
      "Layer 3 (smart summary): <code>"+(m.layer3||"?")+"</code>"+(META.mock?" · <b>mock run</b>":"")+".";
    f.appendChild(p);
    f.appendChild(el("p",null,"Populations — matched (content + highlights): "+META.n_matched+
      " · library-only: "+META.n_library_only+" · highlights-only: "+META.n_highlights_only+
      " · skipped exports: "+META.n_stubs+"."));
    if((META.skipped&&META.skipped.length)||(META.failed&&META.failed.length)){
      var det=el("details","foot"); det.appendChild(el("summary",null,"Skipped & failed documents"));
      if(META.skipped&&META.skipped.length){
        det.appendChild(el("p",null,"Skipped (failed/empty export): "+META.skipped.join("; ")));
      }
      (META.failed||[]).forEach(function(x){ det.appendChild(el("p","err",x.title+" — "+x.error)); });
      f.appendChild(det);
    }
    f.appendChild(el("p",null,"Privacy: everything is local except the model calls — article text "+
      "and highlights are sent to the configured model provider for summarisation and embedding."));
  })();

  render();
})();
</script>
</body>
</html>
"""
