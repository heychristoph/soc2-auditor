// SOC 2 report layout. Content comes from data.json, built by scripts/render.py.
// Change the look here; change wording in report-text.yaml.

#let d = json("data.json")
#let accent = rgb("#1d3557")
#let muted = luma(105)
#let hairline = luma(205)
#let t2 = d.report_type == 2

#set document(title: d.title, author: d.auditor)
#set text(font: "Libertinus Serif", size: 10.5pt, lang: "en")
#set par(justify: true, leading: 0.62em, spacing: 0.95em)
#set list(indent: 1em, spacing: 0.6em)
#set enum(indent: 1em, spacing: 0.6em, numbering: "a.")

#set page(
  paper: "us-letter",
  margin: (x: 1in, top: 1in, bottom: 0.9in),
  background: if not d.final {
    rotate(-40deg, text(size: 110pt, weight: "bold", fill: rgb(0, 0, 0, 14))[DRAFT])
  },
  header: context {
    if counter(page).get().first() > 1 {
      set text(8.5pt, fill: muted)
      d.org
      h(1fr)
      [AI Audit — not an official SOC 2 audit]
      v(-0.4em)
      line(length: 100%, stroke: 0.4pt + hairline)
    }
  },
  footer: context {
    if counter(page).get().first() > 1 {
      set text(8.5pt, fill: muted)
      if d.final [AI Audit. Not an official SOC 2 audit.] else [Draft AI Audit. Not signed. Not an official SOC 2 audit.]
      h(1fr)
      counter(page).display("1 of 1", both: true)
    }
  },
)

#show heading.where(level: 1): it => {
  pagebreak(weak: true)
  block(below: 1.3em, {
    text(9.5pt, tracking: 0.12em, fill: muted, upper(it.supplement))
    v(0.1em)
    text(17pt, weight: "bold", fill: accent, it.body)
    v(-0.2em)
    line(length: 100%, stroke: 0.8pt + accent)
  })
}
#show heading: set text(hyphenate: false)
#set table.cell(breakable: false)
#show heading.where(level: 2): it => block(above: 1.3em, below: 0.7em, text(11.5pt, weight: "bold", fill: accent, it.body))
#show heading.where(level: 3): it => block(above: 1em, below: 0.5em, text(10.5pt, weight: "bold", style: "italic", it.body))
#show outline.entry.where(level: 1): it => block(above: 0.9em, link(it.element.location(), grid(
  columns: (5.5em, 1fr, auto),
  text(weight: "bold", it.element.supplement),
  [#it.element.body #box(width: 1fr, repeat[#h(0.25em).#h(0.25em)])],
  it.page(),
)))

#let blocks(items) = for b in items {
  if b.kind == "heading" {
    heading(level: b.at("level", default: 2), outlined: false, b.text)
  } else if b.kind == "para" {
    par(b.text)
  } else if b.kind == "list" {
    if b.at("enum", default: false) { enum(..b.items) } else { list(..b.items) }
  } else if b.kind == "signature" {
    v(1.6em)
    block(breakable: false, for line in b.lines.filter(l => l != "") [#line \ ])
  }
}

// Cover
#page(header: none, footer: none, margin: (x: 1.1in, y: 1.2in), {
  text(10pt, tracking: 0.14em, fill: muted)[AI AUDIT]
  v(0.35em)
  text(11pt, weight: "bold", fill: rgb("#9b2226"))[Not an official SOC 2 audit]
  v(0.6em)
  text(28pt, weight: "bold", fill: accent, d.org)
  v(0.2em)
  line(length: 35%, stroke: 1.2pt + accent)
  v(1.2em)
  text(13pt, d.title)
  v(0.8em)
  text(12pt, fill: muted, if t2 [Throughout the period #d.period] else [As of #d.period])
  v(1fr)
  text(10pt)[Signed by: *#d.signer_name*, #d.signer_title]
  v(0.25em)
  text(10pt)[#d.report_date]
  v(0.35em)
  text(9pt, fill: muted, d.disclaimer)
  v(0.6em)
  text(9pt, fill: muted, d.restricted)
  if not d.final {
    v(0.8em)
    text(9pt, fill: rgb("#9b2226"), weight: "bold")[DRAFT. Generated #d.generated. Not yet signed by the model that ran the audit.]
  }
})

#block(below: 1.3em, {
  text(17pt, weight: "bold", fill: accent)[Contents]
  v(-0.2em)
  line(length: 100%, stroke: 0.8pt + accent)
})
#outline(title: none, depth: 1, indent: 0pt)

#let numerals = ("I", "II", "III", "IV", "V")

#for (i, s) in d.sections.enumerate() {
  heading(level: 1, supplement: [Section #numerals.at(i)], s.title)
  blocks(s.blocks)
}

// Section IV
#let s4 = d.section4
#heading(level: 1, supplement: [Section IV], s4.title)
#for p in s4.intro { par(p) }

#let ncols = s4.columns.len()
#for g in s4.groups {
  heading(level: 2, outlined: false, g.title)
  for c in g.criteria {
    let rows = if c.rows.len() == 0 {
      (table.cell(colspan: ncols, text(style: "italic", fill: muted)[No controls are mapped to this criterion.]),)
    } else {
      c.rows.map(r => {
        let cells = (text(weight: "bold", r.control), r.activity)
        if t2 {
          cells.push(r.tests.map(t => [#t]).join(parbreak()))
          cells.push(if r.exception { text(fill: rgb("#9b2226"), r.result) } else { r.result })
        }
        cells
      }).flatten()
    }
    block(above: 0.9em, {
      set text(size: 9pt)
      set par(justify: false)
      table(
      columns: if t2 { (0.75in, 1.5fr, 1.8fr, 1.1fr) } else { (0.75in, 1fr) },
      stroke: 0.5pt + hairline,
      inset: 6pt,
      align: left + top,
      table.header(
        table.cell(colspan: ncols, fill: accent, text(fill: white, size: 9.5pt)[*#c.id* #h(0.4em) #c.text]),
        ..s4.columns.map(x => table.cell(fill: luma(238), text(size: 8.5pt, weight: "bold", x))),
      ),
      ..rows,
    )
    })
  }
}

// Section V
#let s5 = d.section5
#heading(level: 1, supplement: [Section V], s5.title)
#par(s5.intro)
#if s5.responses.len() == 0 {
  par(text(style: "italic", s5.none))
} else {
  for r in s5.responses {
    heading(level: 2, outlined: false, [Control #r.control])
    par[*Exception noted:* #r.exception]
    par[*Management's response:* #r.response]
  }
}
