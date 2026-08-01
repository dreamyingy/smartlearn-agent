# PDF Summary Tool - PRD (Product Requirements Document)

## Goal
A command-line tool that reads a PDF file and prints a structured summary with
page-level citations.

## Usage
```
python pdf_summary.py <path-to-pdf>
python pdf_summary.py --help
```
On macOS/Linux the command is `python3`. On Windows inside this repo's venv it is
`python` (or `.venv/Scripts/python.exe`).

Exit codes:

| Code | Meaning |
|------|---------|
| 0    | Summary printed successfully |
| 1    | Input problem (missing path, file not found, not a PDF, no extractable text) |
| 2    | Argument parsing error (raised by argparse itself) |

## Requirements

### Input
1. Accept one positional argument: the path to a PDF file.
2. If no argument is given, print a usage message and exit 1 -- never a traceback.
3. If the path does not exist, is a directory, or is not a readable PDF, print a
   one-line explanation naming the path and exit 1.

### Extraction
4. Extract text from the PDF page by page, keeping track of which page each
   chunk of text came from. Page numbers are 1-based and must match the page
   numbers a human sees in a PDF reader.
5. If the extracted text is empty or whitespace-only across all pages, print:
   `No extractable text found. This looks like a scanned PDF; OCR is not supported.`
   and exit 1 **without calling the LLM**.
6. If the extracted text exceeds the model's input budget, truncate at a page
   boundary and state in the Limitations section which pages were not read.
   Never silently drop content.

### LLM call
7. Send the page-tagged text to an LLM through OpenRouter in a single request.
8. Tag each page in the prompt as `[Page N]` so the model can cite it, mirroring
   the `[Paragraph N]` approach already used in `cli_qa.py`.
9. Use `temperature=0` for reproducible output.

### Output
10. Print exactly three sections, in this order, with these exact headings:
    `Overview`, `Key Points`, `Limitations`. No extra sections, no preamble.
11. Every bullet in `Key Points` must end with at least one `[Page X]` citation.
12. Expected shape:
    ```
    ## Overview
    <2-4 sentences describing what the document is about>

    ## Key Points
    - <point> [Page 1]
    - <point> [Page 3]
    - <point> [Page 3]

    ## Limitations
    - <what this summary does not cover>
    ```

### Safety
13. Never print the API key, and never echo it into an error message.
14. Never print the raw PDF contents during normal operation. Only the summary
    reaches stdout.
15. On a network or API failure, print a short friendly message (error type only, not the exception body) and exit 1.

## Tech Constraints
- Python, single file `pdf_summary.py` at the repo root.
- `python-dotenv` to load `OPENROUTER_API_KEY` from `.env`.
- `openai` SDK with `base_url="https://openrouter.ai/api/v1"`.
- Dependencies installed into the existing `.venv`.
- `.env` is never read manually, never printed, never committed.

## Open Decisions (implementer chooses, and must justify)
- **PDF library.** Not specified on purpose. Choose one (e.g. `pypdf`,
  `pdfplumber`, `PyMuPDF`) and state in the commit message or a comment at the
  top of the file *why* -- weighing install weight, per-page text fidelity,
  license, and whether it preserves page boundaries cleanly. Page-boundary
  fidelity matters most here, because requirement 11 depends on it.

## Out of Scope
- OCR for scanned PDFs.
- Interactive follow-up questions.
- Writing the summary to a file.

## Done When

Each check below is a command with an observable result.

1. **Compiles**
   ```
   python -m py_compile pdf_summary.py
   ```
   Exits 0.

2. **Happy path** -- a short text-based PDF produces all three sections and at
   least one `[Page X]` citation in Key Points:
   ```
   python pdf_summary.py sample.pdf
   ```
   Output contains `## Overview`, `## Key Points`, `## Limitations`, and matches `\[Page [0-9]+\]`.

3. **Citation accuracy** -- for a 3-page PDF where a distinctive fact appears
   only on page 3, the bullet carrying that fact cites `[Page 3]`, not `[Page 1]`.

4. **Missing argument**
   ```
   python pdf_summary.py
   ```
   Prints a usage message, exits 1, and prints no traceback
   (output does not contain `Traceback`).

5. **Nonexistent path**
   ```
   python pdf_summary.py nope.pdf
   ```
   Prints a one-line error naming `nope.pdf`, exits 1, no traceback.

6. **Scanned PDF** -- a PDF with no extractable text prints the OCR limitation
   message and exits 1. Verify no LLM call was made by running it with the key
   blanked; the behavior must be identical:
   ```
   OPENROUTER_API_KEY= python pdf_summary.py scanned.pdf
   ```

7. **Key never printed**
   ```
   python pdf_summary.py sample.pdf | grep -i -e "sk-" -e "OPENROUTER_API_KEY"
   ```
   Returns no matches (grep exits 1).

8. **Git stays clean**
   ```
   git status --short
   ```
   Does not list `.env`.

