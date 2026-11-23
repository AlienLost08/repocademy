# Repocademy: Devpost submission draft

> Fill in the bracketed placeholders before submitting. Don't add numbers you haven't measured.

**Tagline:** Paste a GitHub link, get a guided course on that codebase: chapters, a live
architecture map, instant quizzes and a chat that cites file:line.

**Links:** GitHub: `[REPO URL]` · Demo video: `[VIDEO URL]`

## Inspiration

Developers everywhere learn by reading other people's code: students joining open source,
engineers changing teams, maintainers onboarding contributors. But a large repository gives you
no starting point. Documentation explains how to *use* a project, not how it's *built*, and
asking a chatbot about code it hasn't read leads to confident, wrong answers. We wanted the
orientation a patient senior teammate gives you, available for any public repo, free, and
runnable on an ordinary laptop.

## What it does

Paste any public GitHub URL. Repocademy:

1. **Maps the architecture** with static analysis: modules, imports, calls, inheritance, entry
   points and the most central code (PageRank over the call/import graph).
2. **Writes a learning path**: an overview, the public "front door", a *follow one call* trace
   through the system, chapters for the most important modules, how it's tested, and where to
   go next (TODOs, big functions, undocumented code).
3. **Ties every explanation to real code**: excerpts with line numbers and links to the exact
   commit, plus callers and callees.
4. **Quizzes you, graded instantly**: multiple choice ("which file handles X?", "what does Y
   call?"), put the call path in order, find the hand-off line, and *find the bug*, where we
   plant one realistic mutation in a real function.
5. **Lets you try it**: pure functions run in your browser (Pyodide / Web Worker) with inputs
   taken from the project's own tests. You predict the output first.
6. **Shows an interactive architecture map** (D3): toggle calls and imports, see the traced path,
   and click a file to jump to its chapter.
7. **Answers questions about the repo**: retrieval over the code, then a local model answers
   with `file:line` citations. Citations that don't point inside retrieved code are removed.
8. **Tracks progress** with XP, a progress ring and a finish screen, all stored locally.

## How we built it

* **Backend:** Python + FastAPI. Python is parsed with the `ast` module; JavaScript and
  TypeScript with tree-sitter. A resolver links imports (relative, dotted, `src/` layouts,
  re-exports, `module.exports`) and calls (`self`/`this`, imported names, `module.attr`,
  inherited methods, and a few labelled heuristics). Calls inside `except`/`catch` are tagged,
  so the trace follows the happy path.
* **Planner:** deterministic. Chapters, quizzes, distractors, bug mutations and exercises all come
  from graph facts, so every answer key is correct by construction.
* **AI, kept honest:** local open-weight models through Ollama (we used `qwen2.5-coder` 1.5B/3B
  on CPU), or any OpenAI-compatible endpoint via environment variables, with graceful fallback
  to templates. The model writes short chapter intros from extracted facts only. An intro is
  rejected if it names a symbol that doesn't exist in the repo. Chat citations are validated
  against the retrieved chunks.
* **Frontend:** a dependency-free single-page app (vanilla JS, D3, highlight.js, vendored fonts)
  with a dark glass design.
* **Safety:** GitHub URLs only, shallow clones with symlinks/hooks/submodules/LFS disabled, a
  size cap, and **no repository code is ever executed on the server**.
* **Caching:** courses are cached per commit SHA, and three showcase courses (requests, flask,
  express) ship pre-built.

## Challenges we ran into

* Small models invent function names. We moved everything structural to static analysis and
  added a checker that rejects narration naming anything not in the repo.
* Call graphs from static analysis are noisy: early traces wandered into proxy and
  error-handling code. Scoring hops by centrality, depth and cross-file movement, and
  penalising error paths, gave much more readable traces.
* JavaScript export patterns (`exports = module.exports = createApplication`, prototype
  assignment, re-export chains) each needed handling.
* Bug mutations must be fair: never inside docstrings or strings, and the mutated code must still parse.

## Accomplishments we're proud of

* Courses whose structure is correct regardless of model quality, with the model as an optional extra.
* "Find the bug" and "follow one call", which teach how the code actually flows rather than trivia.
* Everything runs free and locally, without accounts or paid APIs.

## What we learned

* Grounding beats model size: a 3B model writing from verified facts gives more useful text
  than a larger model guessing.
* For code understanding, the graph (who calls whom) is the course outline.

## What's next

* More languages (Go, Rust, Java) through more tree-sitter grammars.
* Courses for a chosen subsystem or pull request ("teach me this PR").
* Shareable course links and classroom mode for maintainers onboarding contributors.

## Related work

DeepWiki and similar tools generate documentation wikis from repositories, and LLM-based
"codebase to tutorial" generators exist too. VS Code CodeTour supports hand-written guided tours.
Repocademy's focus is different: an *interactive course* (quizzes graded from the code itself,
planted-bug exercises, runnable examples, progress tracking) whose structure comes from static
analysis, so it runs free on local models.

## Built with

python, fastapi, tree-sitter, ast, d3.js, highlight.js, pyodide, ollama, qwen2.5-coder, javascript, html, css

## AI assistance disclosure

`[PLACEHOLDER: describe honestly how AI tools were used while building this project, e.g. which
parts were written or reviewed with AI coding assistants, and which were designed/written by the
team. Required by the event rules; fill in before submitting.]`
