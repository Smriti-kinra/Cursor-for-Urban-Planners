#!/usr/bin/env python3
"""
Markdown -> LaTeX -> PDF converter using Pandoc, tuned for documents with
images, tables, code blocks, and math.

Requirements (install once):
    Ubuntu/Debian:
        sudo apt-get install pandoc texlive-xetex texlive-fonts-recommended \
             texlive-latex-extra librsvg2-bin
    macOS:
        brew install pandoc librsvg
        brew install --cask mactex
    Windows:
        choco install pandoc miktex rsvg-convert

Note on images:
  - PNG/JPG/PDF images work out of the box.
  - SVG images need `rsvg-convert` (installed above) so Pandoc can rasterize
    them to PDF before LaTeX embeds them -- plain LaTeX cannot include SVG
    directly.

Usage:
    python md_to_pdf.py input.md                 # -> input.pdf
    python md_to_pdf.py input.md -o output.pdf
    python md_to_pdf.py input.md --tex-only       # only produce .tex, no PDF
    python md_to_pdf.py input.md --bibliography refs.bib --csl ieee.csl
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# LaTeX preamble injected via --include-in-header. This is where the
# image/table/figure fidelity fixes live.
PREAMBLE = r"""
% ---- Images ----
\usepackage{graphicx}
% adjustbox (loaded with [export]) adds "max width"/"max height" keys that
% graphicx understands as *caps*, not fixed sizes: an oversized image is
% scaled down to fit the page, a small image is left at its natural size,
% and any explicit size given in Markdown (e.g. ![x](img.png){width=50%})
% still overrides this default.
\usepackage[export]{adjustbox}
\setkeys{Gin}{max width=\linewidth, max height=0.85\textheight, keepaspectratio}

% Keep figures where you put them in the text instead of floating to the
% top/bottom of a page or to the end of the document.
\usepackage{float}
\let\origfigure\figure
\let\endorigfigure\endfigure
\renewenvironment{figure}[1][2] {
    \expandafter\origfigure\expandafter[H]
} {
    \endorigfigure
}

% ---- Tables ----
\usepackage{booktabs}      % clean horizontal rules (used by Pandoc's default tables)
\usepackage{longtable}     % tables that span multiple pages
\usepackage{array}         % better column formatting
\usepackage{multirow}      % merged row cells, if the source uses raw LaTeX for it
\renewcommand{\arraystretch}{1.2}

% ---- Captions ----
\usepackage{caption}
\captionsetup{font=small, labelfont=bf, margin=1cm}

% ---- Code blocks (used with --listings) ----
\usepackage{xcolor}
\usepackage{listings}
\lstset{
    basicstyle=\ttfamily\small,
    breaklines=true,
    frame=single,
    columns=fullflexible,
    backgroundcolor=\color{black!3}
}

% ---- Misc fidelity ----
\usepackage{microtype}     % better justification / fewer overfull hboxes
\usepackage{hyperref}
\hypersetup{colorlinks=true, linkcolor=blue, urlcolor=blue, citecolor=blue}
"""


def check_pandoc():
    if shutil.which("pandoc") is None:
        sys.exit(
            "Error: pandoc not found. Install it first, e.g.\n"
            "  sudo apt-get install pandoc texlive-xetex texlive-fonts-recommended texlive-latex-extra"
        )
    if shutil.which("rsvg-convert") is None:
        print(
            "Warning: rsvg-convert not found -- SVG images in the Markdown will fail "
            "to embed. Install librsvg2-bin (Linux) or librsvg (macOS) if you use SVGs.",
            file=sys.stderr,
        )


def build_pandoc_command(
    md_file: Path,
    out_file: Path,
    engine: str,
    standalone_tex: bool,
    preamble_path: Path,
    bibliography: str = None,
    csl: str = None,
):
    cmd = [
        "pandoc",
        str(md_file),
        "-o", str(out_file),
        "--standalone",
        "--from=markdown+smart+raw_tex+tex_math_dollars+pipe_tables+grid_tables+table_captions+implicit_figures",
        "--highlight-style=tango",
        "--toc",
        "-N",
        "-V", "geometry:margin=1in",
        "-V", "linkcolor:blue",
        "-V", "fontsize=11pt",
        "--listings",
        # Resolve relative image paths against the Markdown file's own folder,
        # regardless of what directory the script is run from.
        "--resource-path", f".:{md_file.parent}",
        "--include-in-header", str(preamble_path),
    ]

    if bibliography:
        cmd += ["--citeproc", "--bibliography", bibliography]
    if csl:
        cmd += ["--csl", csl]

    if not standalone_tex:
        cmd += ["--pdf-engine", engine]

    return cmd


def convert(
    md_path: str,
    output: str = None,
    tex_only: bool = False,
    engine: str = "xelatex",
    bibliography: str = None,
    csl: str = None,
):
    md_file = Path(md_path)
    if not md_file.exists():
        sys.exit(f"Error: file not found: {md_path}")

    check_pandoc()

    with tempfile.TemporaryDirectory() as tmp:
        preamble_path = Path(tmp) / "preamble.tex"
        preamble_path.write_text(PREAMBLE)

        if tex_only:
            out_file = Path(output) if output else md_file.with_suffix(".tex")
            cmd = build_pandoc_command(
                md_file, out_file, engine, True, preamble_path, bibliography, csl
            )
        else:
            out_file = Path(output) if output else md_file.with_suffix(".pdf")
            cmd = build_pandoc_command(
                md_file, out_file, engine, False, preamble_path, bibliography, csl
            )

        print("Running:", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print("Pandoc failed:\n", result.stderr, file=sys.stderr)
            sys.exit(result.returncode)

    print(f"Success: {out_file}")


def main():
    parser = argparse.ArgumentParser(description="Convert Markdown to LaTeX/PDF via Pandoc")
    parser.add_argument("input", help="Path to the .md file")
    parser.add_argument("-o", "--output", help="Output file path (.pdf or .tex)")
    parser.add_argument("--tex-only", action="store_true", help="Only generate .tex, skip PDF")
    parser.add_argument(
        "--engine",
        default="xelatex",
        choices=["xelatex", "pdflatex", "lualatex"],
        help="LaTeX engine to use for PDF generation (default: xelatex)",
    )
    parser.add_argument("--bibliography", help="Path to a .bib file, for citations like [@key]")
    parser.add_argument("--csl", help="Path to a .csl citation style file (used with --bibliography)")
    args = parser.parse_args()

    convert(args.input, args.output, args.tex_only, args.engine, args.bibliography, args.csl)


if __name__ == "__main__":
    main()
