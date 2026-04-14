"""Interactief testscript voor de adaptieve vragenloop.

Gebruik:
    export ANTHROPIC_API_KEY=sk-ant-...
    .venv/bin/python test_questions.py
    .venv/bin/python test_questions.py "Mijn eigen onderwerp"
"""
import os
import sys

# Stub env vars die main.py verwacht maar we niet nodig hebben voor deze test
os.environ.setdefault("SIGNAL_API_URL", "http://localhost")
os.environ.setdefault("PHONE_NUMBER", "+00000000000")

from bot.main import generate_next_question, generate_summary

TOTAL_QUESTIONS = 3


def run_session(topic: str):
    print(f"\n{'=' * 70}")
    print(f"ONDERWERP: {topic}")
    print('=' * 70)

    history: list[tuple[str, str]] = []
    questions: list[str] = []
    answers: list[str] = []

    for n in range(1, TOTAL_QUESTIONS + 1):
        try:
            q = generate_next_question(topic, history, n, TOTAL_QUESTIONS)
        except Exception as e:
            print(f"FOUT bij vraag {n}: {e}")
            return

        print(f"\nVraag {n}: {q}\n")
        try:
            a = input("Jouw antwoord: ").strip()
        except EOFError:
            print("\n(Geen input — sessie afgebroken)")
            return
        if not a:
            print("(Leeg antwoord — sessie afgebroken)")
            return

        questions.append(q)
        answers.append(a)
        history.append((q, a))

    print(f"\n{'-' * 70}")
    print("Samenvatting genereren...")
    try:
        summary = generate_summary(topic, questions, answers)
        print(f"\n{summary}\n")
    except Exception as e:
        print(f"FOUT bij samenvatting: {e}")


def main():
    if len(sys.argv) > 1:
        topic = " ".join(sys.argv[1:])
    else:
        topic = input("Onderwerp: ").strip()
        if not topic:
            print("Geen onderwerp opgegeven.")
            return
    run_session(topic)


if __name__ == "__main__":
    main()
