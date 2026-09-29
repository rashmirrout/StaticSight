<!-- nav:top -->
📚 [Documentation](../README.md) › 📖 The book › **Preface**
<!-- /nav:top -->

# Preface

This book explains StaticSight from the beginning: the problem it solves, the ideas it is built on, how it works
inside, and where it stops. It is written for three kinds of readers:

- **Users** who want to know what the tools actually do before trusting their answers in a review.
- **Integrators** who connect StaticSight to an AI agent and want to understand what the agent sees and why.
- **Contributors** who want to change or extend it without breaking its promises.

You do not need to know the Model Context Protocol, embeddings or GNU Global to follow it. Each term is explained the
first time it appears. You should be comfortable reading a little C++ and running commands in a terminal.

## How to read it

The chapters are in chronological order: each builds on the previous one, following the path a design takes from a
problem to a working tool.

| Chapter | Question it answers |
|---|---|
| [1. The problem](01-the-problem.md) | Why do AI reviewers miss costly C++ bugs, and what evidence would stop that? |
| [2. Principles](02-principles.md) | Which rules shape every decision in StaticSight? |
| [3. The engines](03-the-engines.md) | Which existing tools provide the evidence, and what does each contribute? |
| [4. Architecture](04-architecture.md) | How are the parts arranged, and why are there two implementations? |
| [5. A review, step by step](05-a-review-step-by-step.md) | What happens, concretely, when you ask for a review? |
| [6. The review tools in depth](06-review-tools-in-depth.md) | How does each tool reach its conclusions, and where can it be wrong? |
| [7. Semantic search](07-semantic-search.md) | How can a tool find code by meaning, offline, and stay fresh? |
| [8. Cross-platform](08-cross-platform.md) | How does the same code give identical answers on Linux and Windows? |
| [9. Trust and testing](09-trust-and-testing.md) | Why can you believe the output, and how is that checked? |
| [10. Using it with AI](10-using-it-with-ai.md) | How do agents, skills and prompts turn evidence into a review? |
| [11. Limits and roadmap](11-limits-and-roadmap.md) | What can it not do, and what comes next? |

If you only have ten minutes, read chapters 1, 2 and 5. If you want to use StaticSight today, start with
[Getting started](../getting-started.md) and come back later.

## Conventions

- Every example output in this book is real. It comes from running StaticSight on its own test repository, a small
  C++ project with deliberately planted review bugs. You can rebuild it with
  `python3 shared/fixtures/make_fixture.py /tmp/cpp-sample` and reproduce every result.
- `staticsight …` means running the launcher: `python3 $SS_HOME/staticsight.py …`, where `SS_HOME` is the folder you cloned StaticSight into.
- File paths in results are relative to the repository being analysed and always use `/`, on every OS.
- "The agent" means the AI assistant in your editor (GitHub Copilot, Claude Code, Cursor, Windsurf, …).
  "The server" means StaticSight.

## A note on honesty

StaticSight does not compile your code. Some of its analyses read text and count braces rather than asking a compiler.
The book says so wherever it matters, and so does every tool output that relies on a heuristic. A review tool that
overstates its certainty is worse than none; this principle comes back in almost every chapter.

---

<!-- nav:bottom -->
|   | 📚 [Documentation](../README.md) | [The problem](01-the-problem.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
