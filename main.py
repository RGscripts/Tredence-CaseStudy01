"""CLI entry point: question -> retrieve -> LLM -> answer.

Tries the deterministic path first (exact, trusted); only falls through to the
LLM planner + generated SQL when nothing deterministic matched -- see
data_engine.py's module docstring for the routing/safety contract.
"""
from data_engine import retrieve, run_planner
from llm import ask_llm


def answer(question: str) -> str:
    context = retrieve(question)
    if context:
        return ask_llm(question, context)

    result = run_planner(question)
    text = result["text"]
    if result["mode"] == "sql":
        text += f"\n\n[Execution plan: {result['plan']}]\n[SQL used: {result['sql']}]"
    return text


def main():
    print("Student Intelligence Assistant (type 'exit' to quit)")
    while True:
        question = input("\nAsk a question: ").strip()
        if not question:
            continue
        if question.lower() in ("exit", "quit"):
            break
        print("\n" + answer(question))


if __name__ == "__main__":
    main()
