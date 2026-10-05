/* ============================================================================
   Guide Check — the analysis page.

   Calls POST /api/check and renders an evidence report. The API contract and
   every number in it are untouched; this file is presentation only. Where a
   quantile or a label is derived here (the interquartile band, the similarity
   step) it is derived from values the API already returned, and the derivation
   is named in the copy so nothing appears to be measured that is not.

   Charts are inline SVG re-rendered on resize. Colours come from CSS custom
   properties, so a theme switch repaints without a redraw. Every chart has a
   text or table twin, so no value is reachable only by hover.
   ========================================================================= */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var last = null;          // most recent payload, for redraw on resize
  var activeComp = -1;      // linked selection between list and locator

  /* ------------------------------------------------------------ format -- */
  var AUD = function (n) {
    if (n == null || !isFinite(n)) return "—";
    return "$" + Math.round(n).toLocaleString("en-AU");
  };
  var compact = function (n) {
    if (n == null || !isFinite(n)) return "—";
    var a = Math.abs(n);
    if (a >= 1e6) return "$" + (n / 1e6).toFixed(a < 1e7 ? 2 : 1).replace(/\.0+$/, "") + "M";
    if (a >= 1e3) return "$" + Math.round(n / 1e3) + "k";
    return "$" + Math.round(n);
  };
  var pct1 = function (n) { return (n == null || !isFinite(n)) ? "—" : n.toFixed(1) + "%"; };
  var day = function (s) { return s ? String(s).slice(0, 10) : "—"; };
  /* isFinite(null) is true — null coerces to 0 — so a missing land area would
     print as "0 m2". Every optional number goes through this. */
  var isNum = function (v) { return v != null && v !== "" && isFinite(v); };
  var ord = function (n) {
    var v = Math.round(n), s = ["th", "st", "nd", "rd"], k = v % 100;
    return v + (s[(k - 20) % 10] || s[k] || s[0]);
  };
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* Linear-interpolated quantile over the adjusted comparables the API
     returned. Presentation of returned values, not a new measurement. */
  function quantile(sorted, q) {
    if (!sorted.length) return NaN;
    var pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    if (lo === hi) return sorted[lo];
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }

  /* ------------------------------------------------------- severity copy -- */
  var SEV = {
    strong:  { word: "Well below the evidence", icon: "alert",    plain: "This guide sits well below what comparable sales support." },
    notable: { word: "Below the evidence",      icon: "alert",    plain: "This guide sits below what comparable sales support." },
    mild:    { word: "At the low end",          icon: "caution",  plain: "This guide sits at the low end of the comparable evidence." },
    none:    { word: "Consistent",              icon: "check",    plain: "This guide is consistent with the comparable sales." },
    unknown: { word: "Not enough evidence",     icon: "question", plain: "There are not enough comparable sales to assess this guide." }
  };

  var ICONS = {
    alert:    '<path d="M7 1.4 13.2 12.4H.8L7 1.4Z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M7 5.6v3.1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="7" cy="10.6" r=".85" fill="currentColor"/>',
    caution:  '<circle cx="7" cy="7" r="5.9" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M7 3.8v3.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="7" cy="9.9" r=".85" fill="currentColor"/>',
    check:    '<circle cx="7" cy="7" r="5.9" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M4.3 7.2 6.2 9.1l3.5-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
    question: '<circle cx="7" cy="7" r="5.9" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M5.5 5.4a1.6 1.6 0 1 1 1.9 1.8v1" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="7" cy="10.2" r=".85" fill="currentColor"/>',
    known:    '<circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M3.6 6.2 5.3 7.9 8.5 4.4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
    limited:  '<circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M3.5 6h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    unknownc: '<circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="2.2 2"/><path d="M4.6 4.7a1.4 1.4 0 1 1 1.7 1.6v.7" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/><circle cx="6" cy="8.6" r=".75" fill="currentColor"/>'
  };

  function sevColour(sev) {
    return sev === "none" ? "var(--good)"
      : sev === "mild" ? "var(--warn)"
      : sev === "strong" ? "var(--alarm-hi)"
      : sev === "notable" ? "var(--alarm)" : "var(--muted)";
  }

  /* ------------------------------------------------------------ tooltip -- */
  var tip = null;
  function showTip(html, x, y) {
    if (!tip) { tip = document.createElement("div"); tip.className = "viz-tip"; document.body.appendChild(tip); }
    tip.innerHTML = html;
    tip.classList.add("show");
    var r = tip.getBoundingClientRect();
    var left = Math.min(Math.max(8, x - r.width / 2), window.innerWidth - r.width - 8);
    var top = y - r.height - 12;
    if (top < 8) top = y + 18;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }
  function hideTip() { if (tip) tip.classList.remove("show"); }

  /* -------------------------------------------------------------- ticks -- */
  function niceTicks(lo, hi, want) {
    var span = hi - lo;
    if (!(span > 0)) return [lo];
    var raw = span / Math.max(1, want);
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var norm = raw / mag;
    var step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
    var out = [], t = Math.ceil(lo / step) * step;
    for (; t <= hi + step * 0.001; t += step) out.push(t);
    return out;
  }

  /* clientWidth includes padding under border-box, so sizing an SVG to it makes
     the SVG wider than the box that holds it. Measure the content width. */
  function innerW(host, min) {
    var cs = window.getComputedStyle(host);
    var w = host.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
    return Math.max(min, Math.round(w) || min);
  }

  var svgNS = "http://www.w3.org/2000/svg";
  function el(name, attrs) {
    var n = document.createElementNS(svgNS, name);
    for (var k in attrs) if (attrs[k] != null) n.setAttribute(k, attrs[k]);
    return n;
  }
  function txt(node, s) { node.textContent = s; return node; }

  /* ==========================================================================
     THE EVIDENCE POSITION — the signature component.

     One money axis carrying four facts at once:
       · the advertised guide            (marked above the axis, in severity colour)
       · the full span of comparables    (thin rule, min to max)
       · the interquartile core          (solid band, p25 to p75)
       · the comparable median           (single strong rule)

     Deliberately not a progress bar: there is no "completion", and the guide can
     legitimately sit outside the evidence in either direction.
     ====================================================================== */
  function drawEvidencePosition(host, d) {
    host.textContent = "";
    var dist = (d.comps_distribution || []).filter(isNum).slice().sort(function (a, b) { return a - b; });
    if (!dist.length) return;

    var guide = d.guide;
    var med = isNum(d.comps_estimate) ? d.comps_estimate : quantile(dist, 0.5);
    var p25 = quantile(dist, 0.25), p75 = quantile(dist, 0.75);
    var minV = dist[0], maxV = dist[dist.length - 1];
    var sev = d.severity || "unknown";
    var col = sevColour(sev);

    var W = innerW(host, 300);
    var narrow = W < 460, wide = W >= 640;

    /* Vertical rhythm scales with width. This is the hero of the report, so on a
       desktop column it gets a taller track and a larger guide figure rather
       than sitting squat inside a 700px box. */
    var F_LAB = narrow ? 9.5 : wide ? 11.5 : 10.5;
    var F_FIG = narrow ? 16 : wide ? 25 : 19;
    var F_EV = narrow ? 12.5 : wide ? 17 : 14;
    var GL_LAB = narrow ? 13 : wide ? 18 : 15;
    var GL_FIG = narrow ? 34 : wide ? 48 : 38;
    var STEM_T = GL_FIG + 9;
    var TRACK_C = narrow ? 80 : wide ? 108 : 88;
    var IQR_H = narrow ? 20 : wide ? 30 : 24;
    var FULL_H = 6;
    var TIP_Y = TRACK_C - IQR_H / 2 - 10;
    var COMP_Y = TRACK_C + IQR_H / 2 + (wide ? 18 : 14);
    var EV_LAB = COMP_Y + (narrow ? 22 : wide ? 32 : 26);
    var EV_FIG = EV_LAB + (narrow ? 17 : wide ? 24 : 19);
    var AXIS_Y = EV_FIG + (narrow ? 20 : wide ? 30 : 24);
    var AXIS_LB = AXIS_Y + 19;
    var H = AXIS_LB + 10;

    /* Domain. A single luxury comparable can be six times the median — scaling
       to the raw extremes then squeezes the guide and the interquartile band
       into the leftmost sliver, which is exactly the part that has to be
       readable. So the axis runs to a Tukey fence instead, and any comparable
       beyond it is counted and declared at the edge rather than silently
       dropped. The guide is always inside the domain, however extreme. */
    var iqr = p75 - p25;
    var dLo = Math.max(minV, p25 - 1.5 * iqr);
    var dHi = Math.min(maxV, p75 + 1.5 * iqr);
    if (isNum(guide)) { dLo = Math.min(dLo, guide); dHi = Math.max(dHi, guide); }
    if (!(dHi > dLo)) { dLo = minV; dHi = maxV || minV + 1; }

    var nBelow = 0, nAbove = 0;
    dist.forEach(function (v) { if (v < dLo) nBelow++; else if (v > dHi) nAbove++; });

    var lo = dLo, hi = dHi;
    var pad = (hi - lo) * 0.12 || Math.max(1, hi * 0.06);
    lo -= pad; hi += pad;

    var ML = 16, MR = 16;
    var x = function (v) {
      var t = (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo);
      return ML + t * (W - ML - MR);
    };

    var aria = "Evidence position. " + dist.length + " adjusted comparable sales span "
      + compact(minV) + " to " + compact(maxV) + ". The middle half sits between "
      + compact(p25) + " and " + compact(p75) + ", median " + compact(med) + "."
      + (isNum(guide) ? " The advertised guide of " + compact(guide) + " sits "
        + (guide < p25 ? "below" : guide > p75 ? "above" : "inside")
        + " that middle half." : "")
      + (nBelow + nAbove > 0 ? " " + (nBelow + nAbove)
        + " outlying comparables fall beyond the axis and are marked at its edge." : "");

    var svg = el("svg", {
      width: W, height: H, viewBox: "0 0 " + W + " " + H,
      role: "img", "aria-label": aria
    });

    /* ---- faint vertical grid, so the eye can carry a value down to the axis */
    /* 4 rather than 3 on narrow: asking for 3 pushes the step up a whole order
       and leaves a $1M / $2M axis, which is too coarse to read a guide against. */
    var ticks = niceTicks(lo, hi, narrow ? 4 : 5);
    ticks.forEach(function (t) {
      var tx = x(t);
      if (tx < ML - 1 || tx > W - MR + 1) return;
      svg.appendChild(el("line", {
        x1: tx, x2: tx, y1: TIP_Y, y2: COMP_Y + 8,
        style: "stroke:var(--grid)", "stroke-width": 1
      }));
    });

    /* ---- full span: a thin rule from the cheapest to the dearest comparable */
    svg.appendChild(el("rect", {
      x: x(minV), y: TRACK_C - FULL_H / 2, width: Math.max(2, x(maxV) - x(minV)),
      height: FULL_H, rx: FULL_H / 2, style: "fill:var(--range)"
    }));
    /* A square end is an end; a chevron means the span runs past the axis. */
    [[minV, nBelow, -1], [maxV, nAbove, 1]].forEach(function (e) {
      var v = e[0], n = e[1], dir = e[2], ex = x(v);
      if (n > 0) {
        svg.appendChild(el("path", {
          d: "M" + (ex - dir * 7) + " " + (TRACK_C - 6) + "L" + ex + " " + TRACK_C
            + "L" + (ex - dir * 7) + " " + (TRACK_C + 6),
          style: "fill:none;stroke:var(--range);stroke-width:2;stroke-linecap:round;stroke-linejoin:round"
        }));
        svg.appendChild(txt(el("text", {
          x: ex - dir * 10, y: TRACK_C - IQR_H / 2 - 7,
          "text-anchor": dir > 0 ? "end" : "start",
          style: "fill:var(--muted);font-family:var(--mono);font-size:" + (narrow ? 9 : 10) + "px"
        }), "+" + n + (dir > 0 ? " higher" : " lower")));
      } else {
        svg.appendChild(el("line", {
          x1: ex, x2: ex, y1: TRACK_C - FULL_H / 2 - 4, y2: TRACK_C + FULL_H / 2 + 4,
          style: "stroke:var(--range)", "stroke-width": 2, "stroke-linecap": "round"
        }));
      }
    });

    /* ---- the interquartile core: where the evidence actually concentrates */
    svg.appendChild(el("rect", {
      x: x(p25), y: TRACK_C - IQR_H / 2, width: Math.max(3, x(p75) - x(p25)),
      height: IQR_H, rx: 3,
      style: "fill:var(--band);fill-opacity:.42;stroke:var(--band);stroke-width:1"
    }));

    /* ---- the median: the single strongest mark on the evidence side */
    var mx = x(med);
    svg.appendChild(el("line", {
      x1: mx, x2: mx, y1: TRACK_C - IQR_H / 2 - 6, y2: TRACK_C + IQR_H / 2 + 6,
      style: "stroke:var(--ink)", "stroke-width": 2
    }));

    /* ---- the individual comparables, as context beneath the band. Off-scale
            ones are already counted at the chevron, so they are not drawn
            piled up against the edge. */
    dist.forEach(function (v) {
      if (v < dLo || v > dHi) return;
      var t = el("line", {
        x1: x(v), x2: x(v), y1: COMP_Y - 5, y2: COMP_Y + 5,
        style: "stroke:var(--dot)", "stroke-width": 1.5, "stroke-linecap": "round"
      });
      t.style.cursor = "crosshair";
      t.addEventListener("mouseenter", function (e) {
        showTip("<b>" + AUD(v) + "</b><br>adjusted comparable", e.clientX, e.clientY);
      });
      t.addEventListener("mouseleave", hideTip);
      svg.appendChild(t);
    });

    /* ---- the evidence bracket label, centred under the interquartile band */
    var bandMid = Math.min(Math.max((x(p25) + x(p75)) / 2, narrow ? 70 : 90), W - (narrow ? 70 : 90));
    svg.appendChild(txt(el("text", {
      x: bandMid, y: EV_LAB, "text-anchor": "middle",
      style: "fill:var(--muted);font-family:var(--mono);font-size:" + F_LAB
        + "px;letter-spacing:.13em"
    }), "COMPARABLE EVIDENCE"));
    svg.appendChild(txt(el("text", {
      x: bandMid, y: EV_FIG, "text-anchor": "middle",
      style: "fill:var(--ink);font-family:var(--mono);font-size:" + F_EV
        + "px;font-weight:500;font-variant-numeric:tabular-nums"
    }), compact(p25) + " – " + compact(p75)));

    /* ---- the guide: marked above, in the severity colour, with a glyph so the
            band is never carried by colour alone */
    if (isNum(guide)) {
      var gx = x(guide);
      var anchor = gx < (narrow ? 62 : 78) ? "start" : gx > W - (narrow ? 62 : 78) ? "end" : "middle";
      var lx = anchor === "start" ? Math.max(ML, gx - 6)
        : anchor === "end" ? Math.min(W - MR, gx + 6) : gx;

      svg.appendChild(txt(el("text", {
        x: lx, y: GL_LAB, "text-anchor": anchor,
        style: "fill:" + col + ";font-family:var(--mono);font-size:" + F_LAB
          + "px;letter-spacing:.13em;font-weight:500"
      }), "ADVERTISED GUIDE"));
      svg.appendChild(txt(el("text", {
        x: lx, y: GL_FIG, "text-anchor": anchor,
        style: "fill:" + col + ";font-family:var(--mono);font-size:" + F_FIG
          + "px;font-weight:600;letter-spacing:-.02em;font-variant-numeric:tabular-nums"
      }), compact(guide)));

      /* stem down to the axis, dashed above the track and solid through it, so
         the guide reads as an external claim being tested against the band */
      svg.appendChild(el("line", {
        x1: gx, x2: gx, y1: STEM_T, y2: TIP_Y - 2,
        style: "stroke:" + col, "stroke-width": 1.5, "stroke-dasharray": "3 3"
      }));
      svg.appendChild(el("path", {
        d: "M" + (gx - 5) + " " + (TIP_Y - 2) + "L" + (gx + 5) + " " + (TIP_Y - 2)
          + "L" + gx + " " + (TIP_Y + 6) + "Z",
        style: "fill:" + col
      }));
      svg.appendChild(el("line", {
        x1: gx, x2: gx, y1: TIP_Y + 5, y2: AXIS_Y,
        style: "stroke:" + col, "stroke-width": 2
      }));
      svg.appendChild(el("circle", {
        cx: gx, cy: TRACK_C, r: 4.5,
        style: "fill:" + col + ";stroke:var(--surface)", "stroke-width": 2
      }));
    }

    /* ---- the money axis */
    svg.appendChild(el("line", {
      x1: ML, x2: W - MR, y1: AXIS_Y, y2: AXIS_Y,
      style: "stroke:var(--rule)", "stroke-width": 1
    }));
    ticks.forEach(function (t) {
      var tx = x(t);
      if (tx < ML - 1 || tx > W - MR + 1) return;
      svg.appendChild(el("line", {
        x1: tx, x2: tx, y1: AXIS_Y, y2: AXIS_Y + 4, style: "stroke:var(--rule)", "stroke-width": 1
      }));
      svg.appendChild(txt(el("text", {
        x: tx, y: AXIS_LB, "text-anchor": "middle",
        style: "fill:var(--muted);font-family:var(--mono);font-size:" + F_LAB
          + "px;font-variant-numeric:tabular-nums"
      }), compact(t)));
    });

    host.appendChild(svg);
  }

  /* ==========================================================================
     THE PROXIMITY LOCATOR

     /api/check returns a distance in kilometres for each comparable but no
     coordinates, so this plots the spatial fact we actually hold rather than
     inventing a map. Markers are linked both ways with the list below.
     ====================================================================== */
  function drawLocator(host, d) {
    host.textContent = "";
    var comps = (d.comps || []).filter(function (c) { return isNum(c.distance); });
    if (!comps.length) return;

    var W = innerW(host, 280);
    var ML = 30, MR = 22, AX = 60, R = 11, CY = 25, H = 84;
    var maxD = Math.max.apply(null, comps.map(function (c) { return c.distance; })) || 1;
    var hi = maxD * 1.15;
    var x = function (v) { return ML + (v / hi) * (W - ML - MR); };

    var svg = el("svg", {
      width: W, height: H, viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Distance of each comparable sale from the subject property: "
        + comps.map(function (c, i) { return (i + 1) + " at " + c.distance.toFixed(2) + " kilometres"; }).join(", ")
    });

    /* axis. The tick label's precision follows the step, so a 0.5 km step is
       never rounded to a repeated whole number — 1.5 printed as "2km" put two
       identical labels on one axis. */
    var ticks = niceTicks(0, hi, 4);
    var step = ticks.length > 1 ? ticks[1] - ticks[0] : hi;
    var dp = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;

    svg.appendChild(el("line", { x1: ML, x2: W - MR, y1: AX, y2: AX, style: "stroke:var(--rule)", "stroke-width": 1 }));
    ticks.forEach(function (t) {
      var tx = x(t);
      if (tx > W - MR + 1) return;
      svg.appendChild(el("line", { x1: tx, x2: tx, y1: AX, y2: AX + 4, style: "stroke:var(--rule)", "stroke-width": 1 }));
      svg.appendChild(txt(el("text", {
        x: tx, y: AX + 18, "text-anchor": "middle",
        style: "fill:var(--muted);font-family:var(--mono);font-size:10px;font-variant-numeric:tabular-nums"
      }), t.toFixed(dp) + " km"));
    });

    /* the subject sits at zero — the anchor everything is measured from */
    svg.appendChild(el("circle", {
      cx: ML, cy: AX, r: 8.5, style: "fill:none;stroke:var(--accent);stroke-opacity:.3", "stroke-width": 1.5
    }));
    svg.appendChild(el("circle", { cx: ML, cy: AX, r: 4.5, style: "fill:var(--accent)" }));

    /* Comparables are nearest neighbours, so they routinely sit within metres of
       each other and every marker lands on the same pixel. Spread the labelled
       markers along a row and lead each one back to its true position, rather
       than stacking them into a single unreadable blob. */
    var lay = comps.map(function (c, i) { return { i: i, c: c, tx: x(c.distance) }; })
      .sort(function (a, b) { return a.tx - b.tx; });
    var gap = R * 2 + 3;
    lay.forEach(function (o, k) {
      o.lx = k === 0 ? Math.max(o.tx, ML + R) : Math.max(o.tx, lay[k - 1].lx + gap);
    });
    for (var k = lay.length - 1; k >= 0; k--) {
      var cap = (k === lay.length - 1) ? W - MR - R : lay[k + 1].lx - gap;
      if (lay[k].lx > cap) lay[k].lx = cap;
    }

    lay.forEach(function (o) {
      var c = o.c, i = o.i;

      var g = el("g", {
        "class": "hit", tabindex: "0", role: "button", "data-i": i,
        "aria-label": "Comparable " + (i + 1) + ", " + (c.address || "") + ", "
          + c.distance.toFixed(2) + " kilometres away. Activate to highlight it in the list."
      });

      /* leader back to the true distance, plus a tick on the axis itself */
      g.appendChild(el("line", {
        x1: o.tx, x2: o.tx, y1: AX - 5, y2: AX + 1, style: "stroke:var(--dot)", "stroke-width": 1.5
      }));
      g.appendChild(el("line", {
        x1: o.tx, x2: o.lx, y1: AX - 5, y2: CY + R,
        style: "stroke:var(--rule)", "stroke-width": 1
      }));
      g.appendChild(el("circle", {
        cx: o.lx, cy: CY, r: R, "data-mark": "1",
        style: "fill:var(--surface);stroke:var(--dot)", "stroke-width": 1.5
      }));
      g.appendChild(txt(el("text", {
        x: o.lx, y: CY + 3.6, "text-anchor": "middle", "data-num": "1",
        style: "fill:var(--ink-2);font-family:var(--mono);font-size:10.5px;pointer-events:none"
      }), String(i + 1)));

      function enter(e) {
        showTip("<b>" + esc(c.address || "") + "</b><br>" + c.distance.toFixed(2) + " km away<br>"
          + AUD(c.sale_price) + " · " + day(c.contract_date),
          e && e.clientX != null ? e.clientX : o.lx, e && e.clientY != null ? e.clientY : CY);
      }
      g.addEventListener("mouseenter", enter);
      g.addEventListener("mouseleave", hideTip);
      g.addEventListener("focus", function () {
        var b = g.getBoundingClientRect();
        showTip("<b>" + esc(c.address || "") + "</b><br>" + c.distance.toFixed(2) + " km away",
          b.left + b.width / 2, b.top + 4);
      });
      g.addEventListener("blur", hideTip);
      g.addEventListener("click", function () { setActive(i, "locator"); });
      g.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); setActive(i, "locator"); }
      });
      svg.appendChild(g);
    });

    /* Say the spatial fact in words too — the axis alone cannot carry it when
       every comparable sits at nearly the same range. */
    var note = $("locatorNote");
    if (note) {
      var ds = comps.map(function (c) { return c.distance; });
      var lo = Math.min.apply(null, ds), hiD = Math.max.apply(null, ds);
      note.textContent = "Distance from the subject property. "
        + (hiD - lo < 0.05
          ? "All " + comps.length + " comparables sit about " + hiD.toFixed(2) + " km away."
          : "They range from " + lo.toFixed(2) + " km to " + hiD.toFixed(2) + " km away.")
        + " No coordinates are published with NSW sales data, so distance is the only spatial"
        + " measure available — this is not a map.";
    }

    host.appendChild(svg);
    paintLocator();
  }

  /* repaint marker styling to match the current selection */
  function paintLocator() {
    var host = $("locator");
    if (!host) return;
    var groups = host.querySelectorAll("g.hit");
    for (var i = 0; i < groups.length; i++) {
      var on = String(activeComp) === groups[i].getAttribute("data-i");
      var mark = groups[i].querySelector('[data-mark]');
      var num = groups[i].querySelector('[data-num]');
      if (mark) {
        mark.setAttribute("style", on
          ? "fill:var(--accent);stroke:var(--accent)"
          : "fill:var(--surface);stroke:var(--dot)");
        mark.setAttribute("stroke-width", on ? 2 : 1.5);
      }
      if (num) {
        num.setAttribute("style", "fill:" + (on ? "var(--on-accent)" : "var(--ink-2)")
          + ";font-family:var(--mono);font-size:10.5px;font-weight:" + (on ? 600 : 400)
          + ";pointer-events:none");
      }
    }
  }

  /* linked selection: list row <-> locator marker */
  function setActive(i, source) {
    activeComp = (activeComp === i) ? -1 : i;
    var rows = document.querySelectorAll("#compsList .comp");
    for (var k = 0; k < rows.length; k++) {
      rows[k].classList.toggle("is-active", k === activeComp);
    }
    paintLocator();
    if (activeComp >= 0 && source === "locator" && rows[activeComp]) {
      rows[activeComp].scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  /* ======================================= diverging drivers (SHAP) ====== */
  function drawDrivers(host, d) {
    host.textContent = "";
    var rows = (d.top_drivers || []).filter(function (r) { return isNum(r.effect_pct); });
    if (!rows.length) return;

    var W = innerW(host, 300);
    var rowH = 46, MT = 26, MB = 10;
    var LABEL = Math.min(190, Math.max(112, W * 0.30));
    var VAL = 62;
    var plotL = LABEL, plotR = W - VAL;
    var H = MT + rows.length * rowH + MB;

    var maxAbs = Math.max.apply(null, rows.map(function (r) { return Math.abs(r.effect_pct); })) || 1;
    var mid = (plotL + plotR) / 2;
    var half = (plotR - plotL) / 2 - 4;
    var x = function (v) { return mid + (v / maxAbs) * half; };

    var svg = el("svg", {
      width: W, height: H, viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Diverging bar chart of the four largest model drivers: "
        + rows.map(function (r) {
          return r.feature + " " + (r.effect_pct >= 0 ? "plus" : "minus") + " "
            + Math.abs(r.effect_pct).toFixed(1) + " per cent";
        }).join(", ")
    });

    svg.appendChild(el("line", {
      x1: mid, x2: mid, y1: MT - 14, y2: H - MB + 2, style: "stroke:var(--rule)", "stroke-width": 1
    }));
    svg.appendChild(txt(el("text", {
      x: mid, y: MT - 19, "text-anchor": "middle",
      style: "fill:var(--muted);font-family:var(--mono);font-size:10px;letter-spacing:.1em"
    }), "NO EFFECT"));

    rows.forEach(function (r, i) {
      var cy = MT + i * rowH + rowH / 2;
      var up = r.effect_pct >= 0;
      var col = up ? "var(--pos)" : "var(--neg)";
      var bx = x(r.effect_pct);
      var bw = Math.max(2, Math.abs(bx - mid));
      var bh = 15, rx = 3;

      var g = el("g", {
        tabindex: "0", role: "listitem",
        "aria-label": r.feature + ", " + r.value + ", " + (up ? "raises" : "lowers")
          + " the estimate by " + Math.abs(r.effect_pct).toFixed(1) + " per cent"
      });

      /* rounded at the data end, square against the zero rule */
      var d0 = up
        ? "M" + (mid + 1) + " " + (cy - bh / 2) + "h" + (bw - rx - 1) + "a" + rx + " " + rx + " 0 0 1 " + rx + " " + rx
          + "v" + (bh - rx * 2) + "a" + rx + " " + rx + " 0 0 1 " + (-rx) + " " + rx + "h" + (-(bw - rx - 1)) + "z"
        : "M" + (mid - 1) + " " + (cy - bh / 2) + "h" + (-(bw - rx - 1)) + "a" + rx + " " + rx + " 0 0 0 " + (-rx) + " " + rx
          + "v" + (bh - rx * 2) + "a" + rx + " " + rx + " 0 0 0 " + rx + " " + rx + "h" + (bw - rx - 1) + "z";
      g.appendChild(el("path", { d: d0, style: "fill:" + col }));

      g.appendChild(txt(el("text", {
        x: LABEL - 16, y: cy - 2, "text-anchor": "end",
        style: "fill:var(--ink);font-family:var(--serif);font-size:14px"
      }), r.feature));
      g.appendChild(txt(el("text", {
        x: LABEL - 16, y: cy + 13, "text-anchor": "end",
        style: "fill:var(--muted);font-family:var(--mono);font-size:11px"
      }), r.value));
      g.appendChild(txt(el("text", {
        x: W - 8, y: cy + 5, "text-anchor": "end",
        style: "fill:var(--ink-2);font-family:var(--mono);font-size:13px;font-variant-numeric:tabular-nums"
      }), (up ? "+" : "−") + Math.abs(r.effect_pct).toFixed(1) + "%"));

      function tipFor(e) {
        var box = g.getBoundingClientRect();
        showTip("<b>" + esc(r.feature) + "</b><br>" + esc(r.value) + "<br>" +
          (up ? "raises" : "lowers") + " the estimate by " + Math.abs(r.effect_pct).toFixed(1) + "%",
          e && e.clientX != null ? e.clientX : box.left + box.width / 2,
          e && e.clientY != null ? e.clientY : box.top + 8);
      }
      g.addEventListener("mouseenter", tipFor);
      g.addEventListener("mouseleave", hideTip);
      g.addEventListener("focus", tipFor);
      g.addEventListener("blur", hideTip);
      svg.appendChild(g);
    });

    host.appendChild(svg);
  }

  /* ============================================ the model's 80% interval == */
  function drawInterval(host, d) {
    host.textContent = "";
    if (!isNum(d.lower) || !isNum(d.upper)) return;
    var W = innerW(host, 280);
    var H = 74, ML = 12, MR = 12, y = 30;
    var lo = d.lower, hi = d.upper, pt = d.point;
    var pad = (hi - lo) * 0.06;
    var a = lo - pad, b = hi + pad;
    var x = function (v) { return ML + (v - a) / (b - a) * (W - ML - MR); };

    var svg = el("svg", {
      width: W, height: H, viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Model interval from " + AUD(lo) + " to " + AUD(hi) + ", point estimate " + AUD(pt)
    });

    svg.appendChild(el("rect", {
      x: x(lo), y: y - 7, width: Math.max(2, x(hi) - x(lo)), height: 14, rx: 3,
      style: "fill:var(--band);fill-opacity:.32;stroke:var(--band);stroke-width:1"
    }));
    [lo, hi].forEach(function (v) {
      svg.appendChild(el("line", {
        x1: x(v), x2: x(v), y1: y - 12, y2: y + 12, style: "stroke:var(--ink-2)", "stroke-width": 1.5
      }));
    });
    svg.appendChild(el("circle", {
      cx: x(pt), cy: y, r: 6, style: "fill:var(--accent);stroke:var(--surface)", "stroke-width": 2
    }));

    [[lo, "start", ML], [hi, "end", W - MR]].forEach(function (p) {
      svg.appendChild(txt(el("text", {
        x: p[2], y: y + 32, "text-anchor": p[1],
        style: "fill:var(--muted);font-family:var(--mono);font-size:11px;font-variant-numeric:tabular-nums"
      }), AUD(p[0])));
    });
    svg.appendChild(txt(el("text", {
      x: Math.min(Math.max(x(pt), 56), W - 56), y: y - 18, "text-anchor": "middle",
      style: "fill:var(--accent);font-family:var(--mono);font-size:11.5px"
    }), "estimate " + compact(pt)));
    host.appendChild(svg);
  }

  /* ==================================== comparables as expandable evidence = */
  /* Similarity is the model's own adjustment magnitude — how far it had to move
     the sale to stand in for the subject. Small adjustment, close comparable.
     No new score is invented; the copy names exactly what is being shown. */
  function similarity(c) {
    var a = isNum(c.adjustment_pct) ? Math.abs(c.adjustment_pct) : null;
    if (a == null) return { step: 0, word: "unknown" };
    if (a < 10) return { step: 4, word: "very close" };
    if (a < 20) return { step: 3, word: "close" };
    if (a < 35) return { step: 2, word: "moderate" };
    return { step: 1, word: "distant" };
  }

  function whyText(c, d, sim) {
    var subj = d.subject || {};
    var bits = [];
    if (isNum(c.distance)) {
      bits.push("It sold <b>" + c.distance.toFixed(2) + " km</b> from the subject"
        + (c.suburb && subj.suburb && String(c.suburb).toUpperCase() !== String(subj.suburb).toUpperCase()
          ? ", in neighbouring " + esc(c.suburb) : ", in the same suburb") + ".");
    }
    if (c.property_type) {
      bits.push("It is the same property type (<b>" + esc(c.property_type) + "</b>) — a house is never compared against a unit.");
    }
    if (isNum(c.land_area_m2) && isNum(subj.land_area_m2) && subj.land_area_m2 > 0) {
      var delta = (c.land_area_m2 - subj.land_area_m2) / subj.land_area_m2 * 100;
      bits.push("Its land area of <b>" + Math.round(c.land_area_m2) + " m²</b> is "
        + (Math.abs(delta) < 5 ? "within 5% of" :
          (Math.abs(delta).toFixed(0) + "% " + (delta > 0 ? "larger than" : "smaller than")))
        + " the subject's " + Math.round(subj.land_area_m2) + " m².");
    } else if (isNum(c.land_area_m2)) {
      bits.push("Its land area is <b>" + Math.round(c.land_area_m2) + " m²</b>; no land area was supplied for the subject, so this could not be compared.");
    }
    if (c.contract_date) {
      bits.push("The contract was dated <b>" + day(c.contract_date) + "</b>, inside the "
        + (d.comps_lookback_days ? (Math.round(d.comps_lookback_days / 365 * 10) / 10) + "-year " : "")
        + "lookback window.");
    }
    var adjLine = "";
    if (isNum(c.adjustment_pct)) {
      adjLine = "To stand in for the subject the model moved this sale by <b>"
        + (c.adjustment_pct >= 0 ? "+" : "−") + Math.abs(c.adjustment_pct).toFixed(1)
        + "%</b>, taking " + AUD(c.sale_price) + " to <b>" + AUD(c.adjusted_price)
        + "</b>. That adjustment is the model's measure of how alike the two properties are — "
        + sim.word + " on this one.";
    }
    return "<p>" + bits.join(" ") + "</p>" + (adjLine ? "<p>" + adjLine + "</p>" : "");
  }

  function renderComps(d) {
    var host = $("compsList");
    host.textContent = "";
    activeComp = -1;

    (d.comps || []).forEach(function (c, i) {
      var sim = similarity(c);
      var up = isNum(c.adjustment_pct) && c.adjustment_pct >= 0;

      var row = document.createElement("div");
      row.className = "comp";

      var bodyId = "compBody" + i;
      var head = document.createElement("button");
      head.type = "button";
      head.className = "comp-head";
      head.setAttribute("aria-expanded", "false");
      head.setAttribute("aria-controls", bodyId);
      head.innerHTML =
        '<span class="comp-rank">' + (i + 1) + "</span>" +
        '<span class="comp-addr-wrap">' +
          '<span class="comp-addr">' + esc(c.address || "Address withheld") + "</span>" +
          '<span class="comp-where">' + esc(c.suburb || "") + " " + esc(c.postcode || "") +
            (isNum(c.distance) ? " · " + c.distance.toFixed(2) + " km" : "") + "</span>" +
        "</span>" +
        '<span class="comp-cells">' +
          '<span class="comp-cell"><span class="lbl">Sold</span><span class="v">' + AUD(c.sale_price) + "</span></span>" +
          '<span class="comp-cell"><span class="lbl">Adjusted</span><span class="v ' +
            (up ? "adj-up" : "adj-down") + '">' + AUD(c.adjusted_price) + "</span></span>" +
          '<span class="comp-cell"><span class="lbl">Similarity</span><span class="v">' +
            '<span class="simbar s' + sim.step + '" role="img" aria-label="Similarity: ' + sim.word + '">' +
              [1, 2, 3, 4].map(function (n) { return '<i class="' + (n <= sim.step ? "on" : "") + '"></i>'; }).join("") +
            '</span> <span class="simword">' + sim.word + "</span></span></span>" +
        "</span>" +
        '<svg class="comp-chev" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m4 6.5 4 4 4-4"/></svg>';

      var body = document.createElement("div");
      body.className = "comp-body";
      body.id = bodyId;
      body.innerHTML =
        '<div class="comp-facts">' +
          '<div><span class="lbl">Sale date</span><span class="v">' + day(c.contract_date) + "</span></div>" +
          '<div><span class="lbl">Distance</span><span class="v">' + (isNum(c.distance) ? c.distance.toFixed(2) + " km" : "—") + "</span></div>" +
          '<div><span class="lbl">Land size</span><span class="v">' + (isNum(c.land_area_m2) ? Math.round(c.land_area_m2) + " m²" : "—") + "</span></div>" +
          '<div><span class="lbl">Type</span><span class="v">' + esc(c.property_type || "—") + "</span></div>" +
          '<div><span class="lbl">Sale price</span><span class="v">' + AUD(c.sale_price) + "</span></div>" +
          '<div><span class="lbl">Adjustment</span><span class="v">' +
            (isNum(c.adjustment_pct) ? (up ? "+" : "−") + Math.abs(c.adjustment_pct).toFixed(1) + "%" : "—") + "</span></div>" +
          '<div><span class="lbl">Adjusted value</span><span class="v">' + AUD(c.adjusted_price) + "</span></div>" +
        "</div>" +
        '<div class="why"><h4>Why this comparable?</h4>' + whyText(c, d, sim) + "</div>";

      head.addEventListener("click", function () {
        var open = row.classList.toggle("is-open");
        head.setAttribute("aria-expanded", open ? "true" : "false");
        setActive(i, "list");
      });

      row.appendChild(head);
      row.appendChild(body);
      host.appendChild(row);
    });
  }

  /* =============================== known / limited / unknown confidence === */
  /* Every note the API returns is a statement about how much we know. Sorting
     them into three named tiers turns a flat caveat list into a confidence
     model the reader can act on — and each tier carries a word and a glyph, so
     the tier is never signalled by colour alone. */
  function renderConfidence(d) {
    var host = $("confList");
    host.textContent = "";
    var items = [];

    var n = d.comps_n || d.comps_total;
    if (isNum(n)) {
      items.push({
        tier: n >= 20 ? "known" : n >= 10 ? "limited" : "unknown",
        text: "<b>" + n + " comparable sales</b> were found for this property type nearby"
          + (isNum(d.comps_spread_pct) ? ", with the middle half spread across "
            + pct1(d.comps_spread_pct) + " of the median" : "") + "."
          + (n >= 20 ? " That is enough for a percentile to be meaningful."
            : " Fewer comparables make the percentile coarse — read it as a direction, not a measurement.")
      });
    }

    if (isNum(d.typical_error_pct)) {
      items.push({
        tier: "limited",
        text: "The model's <b>typical error for " + esc(d.segment || "this segment") + " property is "
          + pct1(d.typical_error_pct) + "</b>. Any gap smaller than that is inside the noise."
      });
    }

    if (d.subject && d.subject.location_basis) {
      items.push({ tier: "limited", text: esc(d.subject.location_basis) });
    }
    if (d.evidence_note) {
      items.push({ tier: isNum(d.evidence_age_days) && d.evidence_age_days > 270 ? "limited" : "known", text: esc(d.evidence_note) });
    } else if (d.comps_cutoff) {
      items.push({
        tier: "known",
        text: "Comparable sales are drawn from the "
          + (d.comps_lookback_days ? (Math.round(d.comps_lookback_days / 365 * 10) / 10) + " years " : "")
          + "up to " + esc(d.comps_cutoff) + "."
      });
    }
    if (d.empirical_coverage_note) {
      items.push({ tier: "known", text: esc(d.empirical_coverage_note) });
    }
    if (d.bed_bath_note) {
      items.push({ tier: "unknown", text: esc(d.bed_bath_note) });
    }
    items.push({
      tier: "unknown",
      text: "<b>Condition, renovation, aspect, view and interior quality are not in the data at all.</b> "
        + "Two identical blocks can differ by a third on these alone, and nothing here can see that."
    });
    items.push({
      tier: "unknown",
      text: "<b>Whether this guide was reasonable when it was set</b> is a question about the agent's own "
        + "estimate at the time of listing. No price model can observe that, and this tool's accuracy "
        + "at answering it has not yet been validated."
    });

    var TIER = {
      known:   { word: "Known",   icon: "known",    cls: "conf-known" },
      limited: { word: "Limited", icon: "limited",  cls: "conf-limited" },
      unknown: { word: "Unknown", icon: "unknownc", cls: "conf-unknown" }
    };
    var order = { known: 0, limited: 1, unknown: 2 };
    items.sort(function (a, b) { return order[a.tier] - order[b.tier]; });

    items.forEach(function (it) {
      var t = TIER[it.tier];
      var li = document.createElement("li");
      li.className = "conf " + t.cls;
      li.innerHTML =
        '<span class="conf-tag"><svg viewBox="0 0 12 12" aria-hidden="true">' + ICONS[t.icon] + "</svg>" + t.word + "</span>" +
        '<span class="conf-text">' + it.text + "</span>";
      host.appendChild(li);
    });
  }

  /* ---------------------------------------------------------- rendering -- */
  function render(d) {
    last = d;
    var sev = d.severity || "unknown";
    var meta = SEV[sev] || SEV.unknown;
    var s = d.subject || {};

    var dist = (d.comps_distribution || []).filter(isNum).slice().sort(function (a, b) { return a - b; });
    var p25 = quantile(dist, 0.25), p75 = quantile(dist, 0.75);

    /* Reveal BEFORE drawing. A hidden container reports clientWidth 0, so every
       chart measured here would silently fall back to its minimum width and be
       laid out for a phone even on a 1500px screen. */
    $("result").hidden = false;
    $("result").classList.remove("stale");
    $("emptyState").hidden = true;

    /* ---- masthead ------------------------------------------------------- */
    /* Suburbs arrive upper-cased from the API, so the tail has to be lowered
       before the word initials go back up, or PARRAMATTA stays shouting. */
    var name = s.suburb
      ? String(s.suburb).toLowerCase().replace(/\b\w/g, function (m) { return m.toUpperCase(); })
      : "This property";
    var addr = s.address && !/entered manually/i.test(s.address) ? s.address : null;
    $("subjectName").textContent = addr ? addr : name;

    var chips = [];
    if (addr && s.suburb) chips.push({ k: "", v: name });
    if (s.postcode) chips.push({ k: "NSW", v: s.postcode });
    if (s.property_type) chips.push({ k: "", v: s.property_type });
    chips.push(isNum(s.land_area_m2) && s.land_area_m2 > 0
      ? { k: "land", v: Math.round(s.land_area_m2) + " m²" }
      : { k: "", v: "land area not supplied", ghost: true });
    if (isNum(s.bedrooms)) chips.push({ k: "bed", v: s.bedrooms, ghost: true });
    if (isNum(s.bathrooms)) chips.push({ k: "bath", v: s.bathrooms, ghost: true });
    if (s.valued_as_at) chips.push({ k: "as at", v: s.valued_as_at });
    $("subjectMeta").innerHTML = chips.map(function (c) {
      return '<span class="chip' + (c.ghost ? " ghost" : "") + '">' +
        (c.k ? '<span class="k">' + esc(c.k) + "</span> " : "") + esc(c.v) + "</span>";
    }).join("");

    $("guideFigure").textContent = AUD(d.guide);
    $("guideSub").textContent = isNum(d.comps_percentile)
      ? ord(d.comps_percentile) + " percentile of the comparable evidence" : "";

    var badge = $("sevBadge");
    badge.className = "sev-badge sev-" + sev;
    badge.innerHTML = '<svg viewBox="0 0 14 14" aria-hidden="true">' + ICONS[meta.icon] + "</svg><span>" + meta.word + "</span>";

    /* ---- 01 evidence position ------------------------------------------- */
    $("epAside").textContent = (d.comps_n || dist.length) + " adjusted comparable sales";
    drawEvidencePosition($("epFigure"), d);

    $("epGuide").textContent = AUD(d.guide);
    $("epGuideCell").style.setProperty("--mark", sevColour(sev));
    $("epGuideN").textContent = isNum(d.comps_percentile) ? ord(d.comps_percentile) + " percentile" : "";
    $("epRange").textContent = dist.length ? compact(p25) + " – " + compact(p75) : "—";
    $("epMedian").textContent = AUD(d.comps_estimate);
    $("epMedianN").textContent = isNum(d.comps_spread_pct) ? pct1(d.comps_spread_pct) + " spread" : "";

    var where = !isNum(d.guide) || !dist.length ? ""
      : d.guide < p25 ? "below" : d.guide > p75 ? "above" : "inside";
    $("epCaption").innerHTML = !where ? "" :
      "The advertised guide of <b>" + AUD(d.guide) + "</b> sits <b>" + where +
      " the middle half</b> of the adjusted comparable sales. " +
      "Of the " + (d.comps_total || dist.length) + " comparables, <b>" + d.comps_below +
      "</b> sold for less than the guide once adjusted to this property.";

    var calc = $("epCalc");
    calc.textContent = "";
    [
      ["Comparable sales used", (d.comps_n || dist.length) + " sales"],
      ["Lookback window", d.comps_lookback_days ? (Math.round(d.comps_lookback_days / 365 * 10) / 10) + " years to " + d.comps_cutoff : "—"],
      ["Lowest adjusted sale", AUD(dist[0])],
      ["25th percentile", AUD(p25)],
      ["Median adjusted sale", AUD(d.comps_estimate)],
      ["75th percentile", AUD(p75)],
      ["Highest adjusted sale", AUD(dist[dist.length - 1])],
      ["Interquartile spread", isNum(d.comps_spread_pct) ? pct1(d.comps_spread_pct) + " of the median" : "—"],
      ["Comparables below the guide", d.comps_below + " of " + d.comps_total],
      ["Guide percentile", isNum(d.comps_percentile) ? ord(d.comps_percentile) : "—"]
    ].forEach(function (r) {
      var li = document.createElement("li");
      li.innerHTML = "<span>" + esc(r[0]) + '</span><span class="v">' + esc(r[1]) + "</span>";
      calc.appendChild(li);
    });

    /* ---- 02 what the evidence shows ------------------------------------- */
    $("findingCard").className = "finding sev-" + sev;
    var plain = meta.plain;
    if (sev !== "unknown" && isNum(d.comps_percentile)) {
      plain = sev === "none"
        ? meta.plain + " " + d.comps_below + " of " + d.comps_total + " comparable sales sold for less than this."
        : meta.plain + " Only " + d.comps_below + " of " + d.comps_total + " comparable sales sold for less.";
    }
    $("findingPlain").textContent = plain;
    $("findingDetail").textContent = d.verdict || "";

    var gap = d.gap_vs_comps_pct;
    var gEl = $("mGap");
    if (!isNum(gap)) {
      gEl.textContent = "—"; gEl.className = "v";
      $("mGapK").textContent = "against the comparables' median";
    } else {
      /* The figure stays a bare percentage so it does not wrap; direction lives
         in the label, because "+36.7%" alone reads as the opposite of what it
         means. Colour follows the SEVERITY, not the raw number — keying it to
         the number once put a 3.3% gap in alarm red under a "consistent"
         verdict, two encodings of the same thing disagreeing. */
      gEl.textContent = Math.abs(gap).toFixed(1) + "%";
      gEl.className = "v " + (sev === "strong" || sev === "notable" ? "neg" : sev === "mild" ? "warn" : "");
      $("mGapK").textContent = (gap >= 0 ? "below" : "above") + " the comparables' median";
    }

    $("mErrs").textContent = isNum(d.gap_in_typical_errors) ? d.gap_in_typical_errors.toFixed(2) + "×" : "—";
    $("mErrsK").textContent = "typical error is " + pct1(d.typical_error_pct) + " for " + (d.segment || "this segment");

    $("mModel").textContent = AUD(d.point);

    $("mPct").textContent = isNum(d.comps_percentile) ? ord(d.comps_percentile) : "—";
    $("mPctK").textContent = "of the adjusted comparable distribution";

    /* ---- 03 comparable sales -------------------------------------------- */
    $("compsIntro").textContent = "Real NSW Valuer General records — the " +
      (d.comps || []).length + " nearest recent sales of the same property type. Each is adjusted " +
      "to the subject by the model, then compared against the guide.";
    renderComps(d);
    drawLocator($("locator"), d);

    var db = $("distBody"); db.textContent = "";
    dist.forEach(function (v, i) {
      var below = (d.guide != null && v < d.guide);
      var tr = document.createElement("tr");
      tr.innerHTML = "<td class='n'>" + (i + 1) + "</td><td class='n'>" + AUD(v) + "</td>" +
        "<td>" + (below ? "below the guide" : "at or above the guide") + "</td>";
      db.appendChild(tr);
    });
    $("distCount").textContent = String(dist.length);

    /* ---- 04 methodology -------------------------------------------------- */
    $("m1sd").textContent = (d.comps_n || 25) + " recent sales of the same property type near the subject.";
    $("m1note").textContent = (d.comps_n || 25) + " comparables drawn from sales up to "
      + (d.comps_cutoff || "the cutoff")
      + (d.comps_lookback_days ? ", a " + (Math.round(d.comps_lookback_days / 365 * 10) / 10) + "-year window." : ".");
    $("m4note").textContent = "This guide of " + AUD(d.guide) + " landed at the "
      + (isNum(d.comps_percentile) ? ord(d.comps_percentile) : "—") + " percentile: "
      + d.comps_below + " of " + d.comps_total + " adjusted comparables sold for less.";
    $("m5note").textContent = isNum(d.gap_in_typical_errors)
      ? "Gap " + pct1(Math.abs(gap)) + " ÷ typical error " + pct1(d.typical_error_pct)
        + " = " + d.gap_in_typical_errors.toFixed(2) + "× typical error."
      : "Not enough evidence to scale the gap.";

    drawDrivers($("driversChart"), d);
    drawInterval($("intervalChart"), d);

    var vb = $("drvBody"); vb.textContent = "";
    (d.top_drivers || []).forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + esc(r.feature) + "</td><td class='n'>" + esc(r.value) + "</td>" +
        "<td class='n'>" + (r.effect_pct >= 0 ? "+" : "−") + Math.abs(r.effect_pct).toFixed(1) + "%</td>";
      vb.appendChild(tr);
    });

    /* ---- 05 what we don't know ------------------------------------------ */
    renderConfidence(d);
    $("disclaimer").textContent = d.disclaimer || "";

    collapseQuery(d);
  }

  function redraw() {
    if (!last) return;
    drawEvidencePosition($("epFigure"), last);
    drawLocator($("locator"), last);
    drawDrivers($("driversChart"), last);
    drawInterval($("intervalChart"), last);
  }

  /* -------------------------------------------- mobile: query collapses --- */
  /* On a small screen the form that produced the answer must not sit on top of
     it. Once a report exists the panel folds into a one-line summary that
     reopens it. Desktop keeps the sticky panel — the rule that hides it lives
     inside a max-width media query, so this class is inert above 1000px. */
  function collapseQuery(d) {
    var grid = $("toolGrid"), panel = $("checkForm"), sum = $("querySummary");
    if (!grid || !panel || !sum) return;
    grid.classList.add("has-result");
    var s = (d && d.subject) || {};
    $("qsTxt").textContent = [
      s.suburb || $("suburb").value,
      s.property_type,
      isNum(s.land_area_m2) && s.land_area_m2 > 0 ? Math.round(s.land_area_m2) + " m²" : null,
      "guide " + compact(d && d.guide)
    ].filter(Boolean).join(" · ");
    if (window.innerWidth <= 1000) {
      panel.classList.add("is-collapsed");
      sum.hidden = false;
    }
  }
  function expandQuery() {
    var panel = $("checkForm"), sum = $("querySummary");
    panel.classList.remove("is-collapsed");
    sum.hidden = true;
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
    setTimeout(function () { $("suburb").focus(); }, 260);
  }

  /* ========================================================== combobox === */
  /* Replaces <datalist>: a listbox we control, with real keyboard navigation,
     a visible chosen state, and match highlighting. Opens as a plain dropdown
     of every suburb when the field is empty and narrows to matches as you
     type; picking one auto-fills the postcode. Falls back to plain typed input
     if the suburb list never loads — the field still submits. */
  var SUBURBS = [];            /* suburb names, upper-case, sorted */
  var POSTCODES = {};          /* suburb name -> its postcode */
  var MAX_OPTS = 60;           /* the list scrolls; no need to build 3,945 rows */

  /* True while the postcode field holds a value this combobox wrote, so
     clearing the suburb can take it back without ever discarding one the user
     typed by hand. */
  var pcAuto = false;

  function pcHelp(show) {
    var h = $("postcodeHelp");
    if (h) h.hidden = !show;
  }

  function setPostcodeFor(name) {
    var pc = POSTCODES[String(name || "").toUpperCase()];
    if (!pc) return;
    var field = $("postcode");
    field.value = pc;
    pcAuto = true;
    pcHelp(true);
    /* brief flash, so a field the user is not looking at still registers */
    field.classList.remove("just-filled");
    void field.offsetWidth;
    field.classList.add("just-filled");
  }

  function clearAutoPostcode() {
    if (!pcAuto) return;
    $("postcode").value = "";
    pcAuto = false;
    pcHelp(false);
  }

  function initCombo() {
    var wrap = $("suburbCombo"), input = $("suburb"), list = $("suburbListbox"),
        clear = $("suburbClear"), toggle = $("suburbToggle");
    var open = false, idx = -1, matches = [];

    /* a postcode typed by hand is the user's; nothing here overwrites it */
    $("postcode").addEventListener("input", function () {
      pcAuto = false;
      pcHelp(false);
    });

    function close() {
      open = false; idx = -1;
      list.hidden = true;
      wrap.classList.remove("is-open");
      input.setAttribute("aria-expanded", "false");
      if (toggle) toggle.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }

    function choose(v) {
      input.value = v;
      wrap.classList.add("is-chosen", "has-value");
      setPostcodeFor(v);
      close();
      input.focus();
    }

    function paint() {
      var items = list.querySelectorAll(".combo-opt");
      for (var i = 0; i < items.length; i++) {
        items[i].setAttribute("aria-selected", i === idx ? "true" : "false");
      }
      if (idx >= 0 && items[idx]) {
        input.setAttribute("aria-activedescendant", items[idx].id);
        items[idx].scrollIntoView({ block: "nearest" });
      } else {
        input.removeAttribute("aria-activedescendant");
      }
    }

    function search(q) {
      q = (q || "").trim().toUpperCase();
      wrap.classList.toggle("has-value", q.length > 0);
      if (!SUBURBS.length) { close(); return; }

      if (!q) {
        /* no query: the dropdown lists the suburbs from the top, so the field
           can be used by browsing as well as by typing */
        matches = SUBURBS.slice(0, MAX_OPTS);
      } else {
        /* prefix matches first — they are almost always what was meant */
        var pre = [], mid = [];
        for (var i = 0; i < SUBURBS.length && pre.length + mid.length < MAX_OPTS; i++) {
          var p = SUBURBS[i].indexOf(q);
          if (p === 0) pre.push(SUBURBS[i]);
          else if (p > 0) mid.push(SUBURBS[i]);
        }
        matches = pre.concat(mid).slice(0, 40);
      }

      list.textContent = "";
      if (!matches.length) {
        var e = document.createElement("li");
        e.className = "combo-empty";
        e.textContent = "No NSW suburb matches “" + q + "”.";
        list.appendChild(e);
      } else {
        matches.forEach(function (m, i) {
          var li = document.createElement("li");
          li.className = "combo-opt";
          li.id = "sub-opt-" + i;
          li.setAttribute("role", "option");
          li.setAttribute("aria-selected", "false");
          var at = q ? m.indexOf(q) : -1;
          var label = at >= 0
            ? esc(m.slice(0, at)) + '<span class="mark">' + esc(m.slice(at, at + q.length)) +
              "</span>" + esc(m.slice(at + q.length))
            : esc(m);
          /* the postcode rides along on the row, so the auto-fill is no surprise */
          li.innerHTML = '<span class="combo-opt-name">' + label + "</span>" +
            '<span class="combo-opt-pc">' + esc(POSTCODES[m] || "") + "</span>";
          /* mousedown, not click: blur would close the list first */
          li.addEventListener("mousedown", function (ev) { ev.preventDefault(); choose(m); });
          list.appendChild(li);
        });
        var hint = document.createElement("li");
        hint.className = "combo-hint";
        hint.setAttribute("aria-hidden", "true");
        hint.innerHTML = "<span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> select</span><span><kbd>Esc</kbd> close</span>";
        list.appendChild(hint);
      }
      idx = -1;
      list.hidden = false;
      open = true;
      wrap.classList.add("is-open");
      input.setAttribute("aria-expanded", "true");
      if (toggle) toggle.setAttribute("aria-expanded", "true");
      paint();
    }

    input.addEventListener("input", function () {
      wrap.classList.remove("is-chosen");
      clearAutoPostcode();
      search(input.value);
    });
    input.addEventListener("focus", function () { search(input.value); });
    /* clicking an already-focused field reopens a list dismissed with Esc */
    input.addEventListener("mousedown", function () {
      if (!open && document.activeElement === input) {
        setTimeout(function () { search(input.value); }, 0);
      }
    });
    input.addEventListener("blur", function () { setTimeout(close, 120); });

    if (toggle) {
      /* mousedown so the input never loses focus to the button */
      toggle.addEventListener("mousedown", function (e) {
        e.preventDefault();
        if (open) { close(); input.focus(); }
        else { input.focus(); search(input.value); }
      });
    }

    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!open) { search(input.value); return; }
        e.preventDefault();
        var n = matches.length;
        if (!n) return;
        idx = e.key === "ArrowDown" ? (idx + 1) % n : (idx <= 0 ? n - 1 : idx - 1);
        paint();
      } else if (e.key === "Enter") {
        if (open && idx >= 0 && matches[idx]) { e.preventDefault(); choose(matches[idx]); }
      } else if (e.key === "Escape") {
        if (open) { e.preventDefault(); close(); }
      } else if (e.key === "Tab") {
        if (open && idx >= 0 && matches[idx]) choose(matches[idx]);
      }
    });

    clear.addEventListener("click", function () {
      input.value = "";
      wrap.classList.remove("is-chosen", "has-value");
      clearAutoPostcode();
      close();
      input.focus();
    });

    /* mark a value set programmatically (presets, deep links) as chosen, and
       fill the postcode when that caller did not supply one of its own */
    input.addEventListener("gc:set", function () {
      wrap.classList.add("has-value");
      if (SUBURBS.indexOf(input.value.toUpperCase()) >= 0) {
        wrap.classList.add("is-chosen");
        if (!($("postcode").value || "").trim()) setPostcodeFor(input.value);
      }
    });
  }

  /* ------------------------------------------------------------ the run -- */
  function num(id) {
    var v = ($(id).value || "").replace(/[^0-9.]/g, "");
    return v === "" ? null : parseFloat(v);
  }

  function run(e) {
    if (e) e.preventDefault();
    var msg = $("formMsg");
    msg.textContent = "";
    $("suburb").setAttribute("aria-invalid", "false");
    $("guide").setAttribute("aria-invalid", "false");

    var suburb = ($("suburb").value || "").trim();
    var guide = num("guide");

    if (!suburb) {
      msg.textContent = "Enter a NSW suburb.";
      $("suburb").setAttribute("aria-invalid", "true"); $("suburb").focus(); return;
    }
    if (!guide) {
      msg.textContent = "Enter the advertised guide price.";
      $("guide").setAttribute("aria-invalid", "true"); $("guide").focus(); return;
    }

    var body = {
      suburb: suburb,
      postcode: ($("postcode").value || "").trim(),
      property_type: $("ptype").value,
      land_area_m2: num("land"),
      guide: guide,
      bedrooms: num("beds"),
      bathrooms: num("baths")
    };

    var btn = $("runBtn");
    btn.disabled = true;
    $("emptyState").hidden = true;
    $("loadingState").hidden = false;
    if (!$("result").hidden) $("result").classList.add("stale");

    fetch("/api/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, d: j }; }); })
      .then(function (res) {
        btn.disabled = false;
        $("loadingState").hidden = true;
        if (!res.ok) {
          $("result").classList.remove("stale");
          msg.textContent = res.d && res.d.error ? res.d.error : "Something went wrong.";
          if (/not found/i.test(msg.textContent)) $("suburb").setAttribute("aria-invalid", "true");
          if ($("result").hidden) $("emptyState").hidden = false;
          return;
        }
        render(res.d);
        if (window.innerWidth <= 1000) {
          $("result").scrollIntoView({ behavior: "smooth", block: "start" });
        }
      })
      .catch(function () {
        btn.disabled = false;
        $("loadingState").hidden = true;
        $("result").classList.remove("stale");
        if ($("result").hidden) $("emptyState").hidden = false;
        msg.textContent = "Could not reach the backend. Is the server running?";
      });
  }

  /* ------------------------------------------------------------- wiring -- */
  function boot() {
    $("checkForm").addEventListener("submit", run);
    initCombo();

    var qs = $("querySummary");
    if (qs) qs.addEventListener("click", expandQuery);

    /* Group the guide price as it is typed. num() strips separators before the
       request, so this is purely how the figure reads back to the person. */
    var gf = $("guide");
    gf.addEventListener("input", function () {
      var digits = gf.value.replace(/[^0-9]/g, "");
      if (!digits) { gf.value = ""; return; }
      var end = gf.selectionStart === gf.value.length;
      gf.value = parseInt(digits, 10).toLocaleString("en-AU");
      if (end) { try { gf.setSelectionRange(gf.value.length, gf.value.length); } catch (e) { /* no-op */ } }
    });

    /* demo presets from the build guide */
    var presets = document.querySelectorAll(".preset-btn");
    for (var i = 0; i < presets.length; i++) {
      presets[i].addEventListener("click", function () {
        var p = this.dataset;
        $("suburb").value = p.suburb || "";
        $("suburb").dispatchEvent(new CustomEvent("gc:set"));
        $("postcode").value = p.postcode || "";
        $("ptype").value = p.ptype || "house";
        $("land").value = p.land || "";
        $("guide").value = p.guide || "";
        run();
      });
    }

    /* suburb list — 3,945 NSW suburbs with their postcodes, fetched once.
       The endpoint returns {suburb, postcode} objects; the plain array of names
       it used to return is still accepted, so a stale cached payload degrades
       to a dropdown without the postcode auto-fill rather than breaking. */
    fetch("/api/suburbs")
      .then(function (r) { return r.json(); })
      .then(function (list) {
        if (!Array.isArray(list)) throw new Error("bad suburb payload");
        SUBURBS = [];
        POSTCODES = {};
        list.forEach(function (row) {
          var name = (typeof row === "string" ? row : (row && row.suburb) || "").toUpperCase();
          if (!name) return;
          SUBURBS.push(name);
          if (row && row.postcode) POSTCODES[name] = String(row.postcode);
        });
        $("suburbHelp").textContent = SUBURBS.length.toLocaleString("en-AU") +
          " NSW suburbs — pick one and the postcode fills itself in.";
        if ($("suburb").value) $("suburb").dispatchEvent(new CustomEvent("gc:set"));
      })
      .catch(function () {
        $("suburbHelp").textContent = "Suburb list unavailable — type the name in full.";
      });

    /* redraw charts on resize (debounced) */
    var t = null;
    window.addEventListener("resize", function () {
      if (!last) return;
      clearTimeout(t);
      t = setTimeout(redraw, 160);
    });

    var pb = $("printBtn");
    if (pb) pb.addEventListener("click", function () { window.print(); });

    /* deep link: /check?suburb=BONDI&guide=1200000 */
    var q = new URLSearchParams(location.search);
    if (q.get("suburb")) {
      $("suburb").value = q.get("suburb");
      $("suburb").dispatchEvent(new CustomEvent("gc:set"));
      if (q.get("postcode")) $("postcode").value = q.get("postcode");
      if (q.get("type")) $("ptype").value = q.get("type");
      if (q.get("land")) $("land").value = q.get("land");
      if (q.get("guide")) { $("guide").value = q.get("guide"); run(); }
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
