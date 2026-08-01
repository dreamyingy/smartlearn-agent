# cli_qa.py
"""Ask questions about a pasted text and get answers with [Paragraph X] citations."""
import argparse
import os
import re
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = "qwen/qwen3.5-flash-02-23"
NOT_FOUND = "The text does not provide this information."

SYSTEM_PROMPT = f"""You are a precise research assistant.

Rules:
1. Answer ONLY using information from the provided text.
2. After EVERY claim, add a citation in the format [Paragraph X], placed before
   the full stop, like this: The sky is blue [Paragraph 1].
3. If a sentence uses information from multiple paragraphs, cite all of them.
4. Cite only the paragraphs that are relevant to the question. Ignore the rest.
5. If the text does not contain the answer, reply with exactly this sentence and
   nothing else:
{NOT_FOUND}
6. Do NOT add any information beyond what is in the text.

Example:
If the text says:
[Paragraph 1] The first algorithm was written by Ada Lovelace in 1843. She based
it on Charles Babbage's Analytical Engine.
[Paragraph 2] Grass is green.

And the question is: 'Who wrote the first algorithm?'
A bare 'Ada Lovelace wrote it [Paragraph 1].' is WRONG -- it drops the second
sentence of Paragraph 1. Your answer should be: 'The first algorithm was written
by Ada Lovelace in 1843 [Paragraph 1]. She based it on Charles Babbage's
Analytical Engine [Paragraph 1].'
Paragraph 2 is irrelevant to the question, so it is not cited."""


def get_client() -> OpenAI:
    """Build the OpenRouter client. Called only when an API request is needed."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is missing. Add it to .env and try again.")
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )


def read_text() -> str:
    """Read lines from the terminal until the user types END on its own line."""
    print("Paste your text. Separate paragraphs with a blank line.")
    print("Type END on its own line when you are done.")
    lines = []
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            break
        if line.strip().upper() == "END":
            break
        lines.append(line)
    return "\n".join(lines)


def split_paragraphs(text: str) -> list:
    """Split text on blank lines into a list of non-empty paragraphs."""
    return [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]


def build_messages(paragraphs: list, question: str) -> list:
    """Number the paragraphs so the model can cite them, then attach the question."""
    numbered = "\n\n".join(
        f"[Paragraph {i}] {p}" for i, p in enumerate(paragraphs, start=1)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{numbered}\n\nQuestion: {question}"},
    ]


def ask(client: OpenAI, messages: list):
    """Send one request. Returns the answer text, or None if the call failed."""
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0,
            max_tokens=500,
        )
    except Exception as exc:
        # Print the error type only -- never the exception body or the client config.
        print(f"Could not reach the model ({type(exc).__name__}). Please try again.")
        return None
    return response.choices[0].message.content


def main() -> int:
    parser = argparse.ArgumentParser(description="CLI Q&A Tool")
    parser.add_argument(
        "--file",
        help="Path to a text file to use as input (instead of pasting)",
    )
    args = parser.parse_args()

    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as exc:
            print(f"Could not read {args.file}: {exc.strerror}")
            return 1
        print(f"Read text from {args.file}.")
    else:
        text = read_text()

    paragraphs = split_paragraphs(text)
    if not paragraphs:
        if args.file:
            print(f"No text found in {args.file}.")
        else:
            print("No text provided. Paste some text, then type END on its own line.")
        return 1

    print(f"\nGot {len(paragraphs)} paragraph(s).")
    print("Ask a question (blank line or 'quit' to exit).")

    client = None
    while True:
        try:
            question = input("\nQuestion (or 'quit'): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() == "quit":
            print("Goodbye!")
            break
        if client is None:
            client = get_client()
        print("Thinking...")
        answer = ask(client, build_messages(paragraphs, question))
        if answer:
            print(f"\n{answer.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
