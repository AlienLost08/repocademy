# Repocademy: Devpost submission draft

> Fill in the bracketed placeholders before submitting. Don't add numbers you haven't measured.

**Tagline:** Paste a GitHub link, get a guided course on that codebase: chapters, a live
architecture map, instant quizzes and a chat that cites file:line.

**Links:** GitHub: https://github.com/AlienLost08/repocademy · Demo video: `[VIDEO URL]`

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
7. **Answers questions about the repo**: the matching code appears instantly, then a small local
   model streams a short answer with `file:line` citations. The prompt includes call-graph facts
   ("X is called by Y at line N"), and afterwards every caller/callee claim in the answer is
   checked against the graph: wrong ones are corrected or dropped, and the UI says how many.
   Citations that don't point at real code are removed.
8. **Tracks progress** with XP, a progress ring and a finish screen, all stored locally.

## How we built it

* **Backend:** Python + FastAPI. Python is parsed with the `ast` module; JavaScript and
  TypeScript with tree-sitter. A resolver links imports (relative, dotted, `src/` layouts,
  re-exports, `module.exports`, `export { x as default }`) and calls (`self`/`this`, imported
  names, `module.attr`, inherited methods, `X.prototype.m`, `fn.call/bind`, and fields typed by the
  constructor that filled them, e.g. `self.adapter = HTTPAdapter()`). JS entry points come from
  `package.json` (`exports`, `main`, `bin`, with `dist/` mapped back to source). Calls inside
  `except`/`catch` are tagged, so the trace follows the happy path.
* **Retrieval:** hybrid scoring: BM25 plus identifier and file-name matching, light stemming and a
  small synonym table, so "how are cookies stored" finds `cookies.py`.
* **Planner:** deterministic. Chapters, quizzes, distractors, bug mutations and exercises all come
  from graph facts, so every answer key is correct by construction.
* **AI, kept honest:** local open-weight models through Ollama (`qwen2.5-coder:1.5b` for chat so it
  answers in seconds on a CPU, `qwen2.5-coder:3b` for intros written once in the background), or
  any OpenAI-compatible endpoint via environment variables, with graceful fallback to templates.
  The model writes short chapter intros from extracted facts only. An intro is rejected if it
  names a symbol that doesn't exist in the repo or says a class has a method it doesn't have.
  Chat answers are post-checked against the call graph and their citations validated.
* **Frontend:** a dependency-free single-page app (vanilla JS, D3, highlight.js, vendored fonts)
  with a dark glass design, a light mode, and a phone layout.
* **Safety:** GitHub URLs only, shallow clones with symlinks/hooks/submodules/LFS disabled, a
  size cap, and **no repository code is ever executed on the server**.
* **Caching:** courses are cached per commit SHA, and four showcase courses (requests, flask,
  express, axios) ship pre-built.

## Challenges we ran into

* Small models invent function names. We moved everything structural to static analysis and
  added a checker that rejects narration naming anything not in the repo.
* Call graphs from static analysis are noisy: early traces wandered into proxy and
  error-handling code. Scoring hops by centrality, depth and cross-file movement, and
  penalising error paths, gave much more readable traces.
* JavaScript export patterns (`exports = module.exports = createApplication`, prototype
  assignment, re-export chains) each needed handling.
* Bug mutations must be fair: never inside docstrings or strings, and the mutated code must still parse.
* A 1.5B model is fast enough for chat but happily says "X is called by Y" when it isn't. Instead
  of a bigger, slower model we check those claims against the static call graph after the answer
  is written.

## Accomplishments we're proud of

* Courses whose structure is correct regardless of model quality, with the model as an optional extra.
* "Find the bug" and "follow one call", which teach how the code actually flows rather than trivia.
* Everything runs free and locally, without accounts or paid APIs.

## What we learned

* Grounding beats model size: a 3B model writing from verified facts gives more useful text
  than a larger model guessing.
* For code understanding, the graph (who calls whom) is the course outline.

## What's next

* Better answers for "how does X work" questions that span several functions (the small model
  still gets some of these wrong where the graph can't check the claim).
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

Built by Satyam Kumar with heavy AI coding assistance. An AI coding agent wrote most of the code,
tests and documentation in this repository, working from Satyam's direction. Satyam chose the idea and
its direction, set the requirements (free, local-first, no invented numbers), tested the app and
reviewed the results. Separately, the app itself uses small local open-weight models
(`qwen2.5-coder` 1.5B/3B via Ollama) at runtime for chapter intros and chat answers, as described above.
