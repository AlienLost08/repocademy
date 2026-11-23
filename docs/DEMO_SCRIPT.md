# Repocademy: demo script (about 2.5 minutes)

**Setup before recording:** `make dev` with Ollama running (`qwen2.5-coder:1.5b` for chat,
`qwen2.5-coder:3b` for intros; the server loads the chat model at start). Open
http://127.0.0.1:8800 in a clean browser profile (or run `localStorage.clear()` in the console).
Zoom the browser to 110% so code is readable. Pre-load one Python exercise once so Pyodide is
cached and doesn't stall on camera. Keep a second tab with the requests repo on GitHub.

---

### 0:00–0:15 · Hook

> *[Show the psf/requests repo on GitHub: 100+ files, scroll the file list.]*
>
> "Every developer knows this moment. You open a codebase you need to work on, and you have
> no idea where to start. The README tells you how to *use* it, not how it's *built*."
>
> *[Switch to Repocademy.]* "So we built a tool that turns any GitHub repo into a course."

### 0:15–0:40 · Paste a link, get a course

> *[Paste `https://github.com/karpathy/micrograd` (or any small repo) and press Generate.]*
>
> "Paste a link. It clones the repo, parses every file with real static analysis (Python's AST and
> tree-sitter for JavaScript and TypeScript), maps what calls what, and plans a course."
>
> *[The progress bar fills while the counters tick up: files parsed, functions & classes, call edges,
> quiz questions.]*
>
> "That took seconds, on a laptop CPU, with no paid API."

### 0:40–1:20 · The course (switch to the requests showcase)

> *[Home → requests card. The overview chapter appears.]* "Here's requests: 13 chapters.
> We start with the big picture: layout, dependencies, how to run it."
>
> *[Click "Follow one call".]* "This is my favourite part. It follows one real call through the
> code: `Session.request` → `Session.send` → `HTTPAdapter.send` → … Every hop shows the exact
> line where the hand-off happens, linked to that commit on GitHub."
>
> *[5-second cut to the axios showcase trace.]* "Same for JavaScript: axios goes
> `createInstance` → `Axios.request` → `Axios._request` → `dispatchRequest`, found from
> `package.json` and the prototype calls, not guessed."
>
> *[Open a module chapter, scroll a code section.]* "Every section is real code with real line
> numbers, plus who calls it and what it calls."

### 1:20–1:50 · Learn by doing

> *[Find-the-bug quiz.]* "Quizzes grade instantly, and they're generated from the code itself.
> Here we planted one bug in a real function. Can you spot it?" *[Click the line → green, with
> the original line shown.]*
>
> *[Exercise.]* "And where a function is pure, you can run it. The inputs come from the
> project's own tests. I predict, I run it right in the browser, and it tells me if I was right.
> Nothing from the repo ever runs on our server."

### 1:50–2:20 · Map + ask the repo

> *[Click 🗺️ Map.]* "The whole architecture as a live graph: files sized by lines, coloured by
> chapter, with the traced path highlighted. Click a file to jump to its chapter."
>
> *[Open chat. Ask: "How does a Session pick the adapter for a URL?"]*
>
> "And you can ask the repo. The matching code shows up instantly, then a small local model
> streams a short answer. Every 'X calls Y' claim is checked against the call graph: wrong ones
> get corrected or dropped, and citations that don't point at real code are removed. That's the
> green 'graph-checked' badge."
>
> *[Click a citation chip → GitHub opens at that line.]*

### 2:20–2:35 · Close

> "Repocademy: any public repo, a guided course in seconds. Free, open source, runs locally.
> The structure comes from static analysis, so a small model can't make it wrong.
> Onboarding for every codebase, for everyone."

---

**Tips**

* If the chat model is slow on the recording machine, ask the question first, then talk over the
  map while it streams, and switch back.
* Don't claim speed numbers you didn't measure on the recording machine. Showing the timer in
  the build overlay is enough.
* Have the `axios` or `express` showcase ready to show that JavaScript works too (a 5-second cut is enough).
* Optional flourish: toggle light mode (☀ in the top bar) or show the phone layout (devtools device mode).
* Ask the chat question from the script once before recording: answers are cached, so the
  on-camera one is instant and already checked. Re-read it on camera before trusting it: the
  small model can still be wrong about details the graph can't check.
