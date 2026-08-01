# pdf_summary.py
"""Summarise a PDF into Overview / Key Points / Limitations with [Page N] citations.

PDF library choice: pdfplumber.

Why: this tool's correctness hinges on requirement 11 -- every Key Points bullet
must carry the page it came from -- so page-boundary fidelity outranks everything
else. pdfplumber exposes the document as `pdf.pages`, and `page.extract_text()`
never reaches across a page break, so the page number attached to each chunk is
structural rather than reconstructed. On top of that it sorts text by layout
position instead of raw content-stream order, which keeps multi-column lecture
slides readable; pypdf, the lighter alternative, tends to jumble those. License is
MIT.

Limitation: pdfplumber is the heavy option. It pulls in pdfminer.six, Pillow,
cryptography and pypdfium2 (~20 MB), and it is markedly slower than pypdf --
roughly a tenth of a second per page, which is noticeable on a 200-page deck. It
also cannot read scanned pages at all; those are rejected up front (requirement 5).
"""
import argparse
import os
import re
import sys

import pdfplumber
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = "qwen/qwen3.5-flash-02-23"


# Character budget for the prompt. MODEL takes a million tokens of context, and at
# roughly 4 characters per token this cap is about 200k of them -- a fifth of the
# window, which fits any realistic deck or paper whole. It exists to stop a
# pathological input, not to trim ordinary documents. Counted in characters because
# adding a tokenizer dependency just to measure the cutoff is not worth it.
MAX_CHARS = 800_000

# Output budget. A ten-page document yields a long Key Points list, and a summary
# that runs past this limit comes back cut off mid-sentence.
MAX_OUTPUT_TOKENS = 2_000

SCANNED_MESSAGE = (
    "No extractable text found. "
    "This looks like a scanned PDF; OCR is not supported."
)

SYSTEM_PROMPT = """You are a precise summariser of lecture material.

The user's document is supplied page by page, each page tagged like [Page 3].

Output rules:
1. Print exactly three sections, in this order, using these exact headings:
## Overview
## Key Points
## Limitations
2. Print nothing else. No preamble, no closing remark, no extra sections.
3. Overview is 2-4 sentences describing what the document is about. It carries no
   citations.
4. Key Points is a list of '- ' bullets. EVERY bullet must end with at least one
   citation in the form [Page X], after the full stop.
5. Cite the page the information actually appears on. If a bullet draws on two
   pages, cite both, like [Page 2] [Page 5].
6. Never cite a page number that was not given to you.
7. Limitations is a list of '- ' bullets saying what the summary does not cover.
8. Use only what the document says. Add nothing from outside it.

Example of a correct Key Points bullet:
- Backpropagation applies the chain rule backwards through the layers. [Page 2]

The same bullet written wrongly, because the citation is missing:
- Backpropagation applies the chain rule backwards through the layers."""


def get_client() -> OpenAI:
    """Build the OpenRouter client. Called only when an API request is needed."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is missing. Add it to .env and try again.")
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )


def parse_page_range(value: str):
    """Turn '2-7' into (2, 7). Returns None if the text is not a usable range."""
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", value)
    if not match:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    if start < 1 or start > end:
        return None
    return start, end


def extract_pages(path: str, page_range=None) -> tuple:
    """Return ([(page_number, text)], total_page_count) for pages that hold text.

    Page numbers are 1-based, matching what a PDF reader shows. page_range, when
    given, is an inclusive (start, end) pair; pages outside it are skipped. The
    total count covers the whole file, including pages holding no text, so the
    caller can tell 'page does not exist' apart from 'page has no text'."""
    pages = []
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        for number, page in enumerate(pdf.pages, start=1):
            if page_range and not page_range[0] <= number <= page_range[1]:
                continue
            text = (page.extract_text() or "").strip()
            if text:
                pages.append((number, text))
    return pages, total


def apply_budget(pages: list) -> tuple:
    """Cut the page list to fit MAX_CHARS, always on a page boundary.

    Returns (kept, dropped_numbers). The first page is kept even if it alone
    exceeds the budget, because sending nothing would be worse than sending one
    oversized page."""
    kept = []
    used = 0
    for index, (number, text) in enumerate(pages):
        # +12 covers the '[Page N] ' tag and the blank line between pages.
        cost = len(text) + 12
        if index > 0 and used + cost > MAX_CHARS:
            return kept, [n for n, _ in pages[index:]]
        kept.append((number, text))
        used += cost
    return kept, []


def format_page_list(numbers: list) -> str:
    """Collapse [4, 5, 6, 9] into '4-6, 9' for a readable Limitations note."""
    if not numbers:
        return ""
    spans = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        spans.append((start, previous))
        start = previous = number
    spans.append((start, previous))
    return ", ".join(
        str(low) if low == high else f"{low}-{high}" for low, high in spans
    )


def build_messages(pages: list) -> list:
    """Tag every page so the model can cite it."""
    tagged = "\n\n".join(f"[Page {number}] {text}" for number, text in pages)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": tagged},
    ]


def summarise(client: OpenAI, messages: list):
    """Send one request. Returns the summary text, or None if the call failed."""
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
    except Exception as exc:
        # Print the error type only -- never the exception body or the client config,
        # either of which could carry the API key.
        print(f"Could not reach the model ({type(exc).__name__}). Please try again.")
        return None

    choice = response.choices[0]
    content = (choice.message.content or "").strip()
    if not content:
        # Say so out loud. Returning None silently here left the user staring at a
        # blank terminal with nothing to debug.
        print(
            f"The model returned an empty summary (finish_reason: "
            f"{choice.finish_reason}). Please try again."
        )
        return None
    if choice.finish_reason == "length":
        print(
            "Warning: the summary reached the output limit and may be cut off.",
            file=sys.stderr,
        )
    return content


def add_truncation_note(summary: str, dropped: list) -> str:
    """State the pages that were never read, rather than trusting the model to.

    Appends to the model's Limitations section, or adds the section if the model
    left it out."""
    if not dropped:
        return summary
    note = (
        f"- Pages {format_page_list(dropped)} were not read: the document exceeded "
        f"the input budget, so it was truncated at a page boundary."
    )
    if re.search(r"^##\s*Limitations\s*$", summary, flags=re.MULTILINE):
        return f"{summary.rstrip()}\n{note}"
    return f"{summary.rstrip()}\n\n## Limitations\n{note}"


def warn_about_citations(summary: str, pages: list) -> None:
    """Requirement 11 is enforced by the prompt, not by us. Check it anyway and
    warn on stderr so the failure is visible without polluting stdout."""
    section = re.search(
        r"^##\s*Key Points\s*$(.*?)(?=^##\s|\Z)",
        summary,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not section:
        print("Warning: the model did not return a Key Points section.", file=sys.stderr)
        return

    valid = {number for number, _ in pages}
    for line in section.group(1).splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        cited = re.findall(r"\[Page (\d+)\]", line)
        if not cited:
            print(f"Warning: bullet has no citation: {line}", file=sys.stderr)
            continue
        unknown = [n for n in cited if int(n) not in valid]
        if unknown:
            print(
                f"Warning: bullet cites page(s) not in the document: {line}",
                file=sys.stderr,
            )


def main() -> int:
    # Piped or redirected output on Windows falls back to the legacy code page
    # (GBK here), which cannot encode the maths symbols that fill research papers.
    # Degrade those characters to '?' instead of dying with a traceback.
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(
        description="Summarise a PDF into Overview / Key Points / Limitations "
        "with [Page N] citations.",
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        help="Path to the PDF file to summarise",
    )
    parser.add_argument(
        "--pages",
        metavar="START-END",
        help="Summarise only this inclusive page range, for example 1-5. "
        "Defaults to the whole document.",
    )
    args = parser.parse_args()

    # A required positional would make argparse exit 2 here; the spec asks for a
    # usage message and exit 1.
    if not args.pdf_path:
        print(parser.format_usage().strip())
        print("Give me the path to a PDF file. Try --help for details.")
        return 1

    page_range = None
    if args.pages is not None:
        page_range = parse_page_range(args.pages)
        if page_range is None:
            print(
                f"Could not read --pages {args.pages}. Give an inclusive range "
                "like 1-5, counting from page 1, with the start no later than "
                "the end."
            )
            return 1

    path = args.pdf_path
    if not os.path.exists(path):
        print(f"No such file: {path}")
        return 1
    if os.path.isdir(path):
        print(f"{path} is a directory, not a PDF file.")
        return 1

    try:
        pages, total = extract_pages(path, page_range)
    except Exception as exc:
        # Covers corrupt files, non-PDF files and password-protected PDFs alike.
        print(f"Could not read {path} as a PDF ({type(exc).__name__}).")
        return 1

    if page_range and page_range[1] > total:
        print(f"{path} has only {total} page(s), so --pages {args.pages} is out of range.")
        return 1

    if not pages:
        if page_range:
            # Saying 'scanned PDF' here would be a wrong diagnosis: the pages exist,
            # they just hold no text.
            print(f"No extractable text on pages {args.pages} of {path}.")
        else:
            print(SCANNED_MESSAGE)
        return 1

    # Everything above this line runs without an API key, so a scanned PDF
    # behaves identically whether or not the key is set.
    kept, dropped = apply_budget(pages)
    print(f"Read {len(kept)} page(s) from {path}. Summarising...\n")

    client = get_client()
    summary = summarise(client, build_messages(kept))
    if summary is None:
        return 1

    summary = add_truncation_note(summary.strip(), dropped)
    print(summary)
    warn_about_citations(summary, kept)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
