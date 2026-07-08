"""
latex_exporter.py — Markdown → LaTeX document compiler.

Converts structured Markdown text (headings, lists, tables, bold/italic,
code blocks, blockquotes) into a clean article-class LaTeX document
suitable for pdflatex compilation.
"""
from __future__ import annotations
import re
from pathlib import Path


# ── LaTeX special-character escaping ─────────────────────────────────────────

_ESCAPE_TABLE = str.maketrans({
    "&":  r"\&",
    "%":  r"\%",
    "$":  r"\$",
    "#":  r"\#",
    "_":  r"\_",
    "{":  r"\{",
    "}":  r"\}",
    "~":  r"\textasciitilde{}",
    "^":  r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
})


def _esc(text: str) -> str:
    """Escape LaTeX special characters in plain text."""
    return text.translate(_ESCAPE_TABLE)


# ── Inline styling parser ─────────────────────────────────────────────────────

_INLINE_RE = re.compile(
    r"(\*\*\*(?P<bi>.+?)\*\*\*"       # bold-italic
    r"|\*\*(?P<b>.+?)\*\*"             # bold
    r"|\*(?P<i>.+?)\*"                 # italic
    r"|`(?P<code>.+?)`"                # inline code
    r"|!\[(?P<alt>[^\]]*)\]\((?P<img>[^)]+)\)"  # image
    r"|\[(?P<lt>[^\]]+)\]\((?P<lhref>[^)]+)\)"  # link
    r")"
)


def _inline(text: str) -> str:
    """Convert inline Markdown to LaTeX commands."""
    result = []
    last_end = 0
    for m in _INLINE_RE.finditer(text):
        # Escape plain text before this match
        result.append(_esc(text[last_end:m.start()]))
        if m.group("bi"):
            result.append(r"\textbf{\textit{" + _esc(m.group("bi")) + r"}}")
        elif m.group("b"):
            result.append(r"\textbf{" + _esc(m.group("b")) + r"}")
        elif m.group("i"):
            result.append(r"\textit{" + _esc(m.group("i")) + r"}")
        elif m.group("code"):
            result.append(r"\texttt{" + _esc(m.group("code")) + r"}")
        elif m.group("img"):
            alt = _esc(m.group("alt") or "Figure")
            # Embedded figure reference
            result.append(
                "\n\\begin{figure}[h!]\n"
                "  \\centering\n"
                f"  % \\includegraphics[width=0.8\\linewidth]{{{m.group('img')}}}\n"
                f"  \\caption{{{alt}}}\n"
                "\\end{figure}\n"
            )
        elif m.group("lhref"):
            result.append(r"\href{" + m.group("lhref") + r"}{" + _esc(m.group("lt")) + r"}")
        last_end = m.end()
    result.append(_esc(text[last_end:]))
    return "".join(result)


# ── LaTeX preamble ────────────────────────────────────────────────────────────

def _build_preamble(title: str, author: str = "Urban Planning AI", date: str = r"\today") -> str:
    escaped_title = _esc(title)
    return rf"""
\documentclass[12pt,a4paper]{{article}}

% ── Package declarations ──────────────────────────────────────────────────────
\usepackage[a4paper, margin=2.5cm]{{geometry}}
\usepackage[T1]{{fontenc}}
\usepackage[utf8]{{inputenc}}
\usepackage{{lmodern}}
\usepackage{{microtype}}
\usepackage{{setspace}}
\usepackage{{parskip}}
\usepackage{{titlesec}}
\usepackage{{booktabs}}
\usepackage{{longtable}}
\usepackage{{array}}
\usepackage{{xcolor}}
\usepackage{{listings}}
\usepackage{{graphicx}}
\usepackage{{hyperref}}
\usepackage{{fancyhdr}}
\usepackage{{mdframed}}
\usepackage{{enumitem}}

% ── Colors ────────────────────────────────────────────────────────────────────
\definecolor{{accentblue}}{{HTML}}{{1E40AF}}
\definecolor{{lightgray}}{{HTML}}{{F8FAFC}}
\definecolor{{bordercolor}}{{HTML}}{{CBD5E1}}
\definecolor{{codetext}}{{HTML}}{{1E293B}}

% ── Section heading styles ────────────────────────────────────────────────────
\titleformat{{\section}}
  {{\color{{accentblue}}\large\bfseries}}
  {{\thesection.}}{{0.8em}}{{}}[\color{{bordercolor}}\titlerule]

\titleformat{{\subsection}}
  {{\color{{accentblue}}\normalsize\bfseries}}
  {{\thesubsection}}{{0.6em}}{{}}

\titleformat{{\subsubsection}}
  {{\normalsize\bfseries\itshape}}
  {{}}{{0em}}{{}}

% ── Line spacing ──────────────────────────────────────────────────────────────
\setstretch{{1.15}}

% ── Hyperlinks ────────────────────────────────────────────────────────────────
\hypersetup{{
  colorlinks=true,
  linkcolor=accentblue,
  urlcolor=accentblue,
  citecolor=accentblue
}}

% ── Header / footer ──────────────────────────────────────────────────────────
\pagestyle{{fancy}}
\fancyhf{{}}
\fancyhead[L]{{\small\color{{accentblue}}\textbf{{Urban Planning Report}}}}
\fancyhead[R]{{\small\color{{gray}}{escaped_title}}}
\fancyfoot[C]{{\small\thepage}}
\renewcommand{{\headrulewidth}}{{0.4pt}}

% ── Code listing style ────────────────────────────────────────────────────────
\lstset{{
  basicstyle=\small\ttfamily\color{{codetext}},
  backgroundcolor=\color{{lightgray}},
  frame=single,
  rulecolor=\color{{bordercolor}},
  breaklines=true,
  xleftmargin=1em,
  xrightmargin=1em,
  aboveskip=0.8em,
  belowskip=0.8em
}}

% ── Table column types ────────────────────────────────────────────────────────
\newcolumntype{{L}}{{>{{\raggedright\arraybackslash}}p{{1.0\\textwidth}}}}

% ── Document metadata ─────────────────────────────────────────────────────────
\title{{\color{{accentblue}}\textbf{{{escaped_title}}}}}
\author{{{_esc(author)}}}
\date{{{date}}}

\begin{{document}}
\maketitle
\thispagestyle{{fancy}}
\tableofcontents
\newpage
""".lstrip()


# ── Table parser ─────────────────────────────────────────────────────────────

def _parse_table_block(rows: list[list[str]]) -> str:
    """Convert a list of row-cell lists into a LaTeX longtable."""
    if not rows:
        return ""
    col_count = max(len(r) for r in rows)
    col_spec = "|" + "|".join(["l"] * col_count) + "|"
    lines = [
        "\\begin{longtable}{" + col_spec + "}",
        "\\hline",
    ]
    for row_idx, row in enumerate(rows):
        padded = row + [""] * (col_count - len(row))
        cells = " & ".join(_inline(c) for c in padded)
        if row_idx == 0:
            lines.append(f"\\textbf{{{cells.replace(' & ', '} & \\textbf{')}}} \\\\")
            lines.append("\\hline\\hline")
        else:
            lines.append(cells + " \\\\")
            lines.append("\\hline")
    lines.append("\\end{longtable}")
    return "\n".join(lines)


# ── Main compiler ─────────────────────────────────────────────────────────────

def markdown_to_latex(markdown_text: str, title: str = "Urban Planning Report") -> str:
    """
    Parse Markdown and generate a complete LaTeX document string.
    Handles: headings (H1–H6), bullet/numbered lists, tables,
    blockquotes, fenced code blocks, bold, italic, inline code, links, images.
    """
    heading_map = {
        1: r"\section",
        2: r"\subsection",
        3: r"\subsubsection",
        4: r"\paragraph",
        5: r"\subparagraph",
        6: r"\textbf",
    }

    lines = markdown_text.splitlines()
    body: list[str] = []

    i = 0
    in_table = False
    table_rows: list[list[str]] = []
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    list_depth = 0

    def flush_table():
        nonlocal table_rows, in_table
        if table_rows:
            body.append(_parse_table_block(table_rows))
        table_rows = []
        in_table = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ── Fenced code block ──────────────────────────────────────────────────
        if stripped.startswith("```"):
            if in_table:
                flush_table()
            if not in_code:
                in_code = True
                code_lang = stripped[3:].strip()
                code_lines = []
            else:
                in_code = False
                lang_opt = f"language={code_lang}" if code_lang else ""
                opt = f"[{lang_opt}]" if lang_opt else ""
                body.append(f"\\begin{{lstlisting}}{opt}")
                body.extend(code_lines)
                body.append("\\end{lstlisting}")
                code_lines = []
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        # ── Table row ─────────────────────────────────────────────────────────
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            is_sep = all(re.match(r"^:?-+:?$", c) for c in cells) if cells else False
            if not is_sep:
                table_rows.append(cells)
            in_table = True
            i += 1
            continue
        elif in_table:
            flush_table()

        # ── Empty line ────────────────────────────────────────────────────────
        if not stripped:
            body.append("")
            i += 1
            continue

        # ── Blockquote ────────────────────────────────────────────────────────
        if stripped.startswith(">"):
            quote_text = stripped.lstrip(">").strip()
            body.append(
                "\\begin{mdframed}[backgroundcolor=lightgray,"
                "linecolor=bordercolor,linewidth=1pt]\n"
                f"\\textit{{{_inline(quote_text)}}}\n"
                "\\end{mdframed}"
            )
            i += 1
            continue

        # ── Horizontal rule ───────────────────────────────────────────────────
        if re.match(r"^[-*_]{3,}$", stripped):
            body.append("\\vspace{0.5em}\\hrule\\vspace{0.5em}")
            i += 1
            continue

        # ── Headings ─────────────────────────────────────────────────────────
        hm = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if hm:
            level = len(hm.group(1))
            text = hm.group(2)
            cmd = heading_map.get(level, r"\subparagraph")
            if level <= 3:
                body.append(f"{cmd}{{{_inline(text)}}}")
            else:
                body.append(f"{cmd}{{{_inline(text)}}}\\\\")
            i += 1
            continue

        # ── Bullet list ───────────────────────────────────────────────────────
        bm = re.match(r"^(\s*)[-*+]\s+(.*)", line)
        if bm:
            indent = len(bm.group(1)) // 2
            text = bm.group(2)
            # Check previous / next for list context
            prev_is_list = body and (body[-1].startswith("\\item") or body[-1] == "\\begin{itemize}")
            if not prev_is_list:
                body.append("\\begin{itemize}[noitemsep, topsep=4pt]")
            body.append(f"  \\item {_inline(text)}")
            # Peek at next line to close list
            next_stripped = lines[i+1].strip() if i+1 < len(lines) else ""
            if not (next_stripped.startswith("-") or next_stripped.startswith("*") or next_stripped.startswith("+")):
                body.append("\\end{itemize}")
            i += 1
            continue

        # ── Numbered list ─────────────────────────────────────────────────────
        nm = re.match(r"^(\s*)\d+\.\s+(.*)", line)
        if nm:
            text = nm.group(2)
            prev_is_enum = body and (body[-1].startswith("\\item") or body[-1] == "\\begin{enumerate}")
            if not prev_is_enum:
                body.append("\\begin{enumerate}[noitemsep, topsep=4pt]")
            body.append(f"  \\item {_inline(text)}")
            next_stripped = lines[i+1].strip() if i+1 < len(lines) else ""
            if not re.match(r"^\d+\.", next_stripped):
                body.append("\\end{enumerate}")
            i += 1
            continue

        # ── Default paragraph ─────────────────────────────────────────────────
        body.append(_inline(stripped))
        i += 1

    # Flush any remaining table
    if in_table:
        flush_table()

    return (
        _build_preamble(title)
        + "\n".join(body)
        + "\n\n\\end{document}\n"
    )


def save_latex(markdown_text: str, output_path: str, title: str = "Urban Planning Report") -> None:
    """Write a LaTeX file from Markdown content."""
    latex = markdown_to_latex(markdown_text, title=title)
    Path(output_path).write_text(latex, encoding="utf-8")
