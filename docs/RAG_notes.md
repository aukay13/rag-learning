# RAG Learning Project — Concept Notes

Understanding Retrieval-Augmented Generation from first principles.

---

## 1. What RAG is, and why it exists

An LLM only knows what was in its training data, frozen at a cutoff date. It has no access to
your private notes, internal docs, or anything created after training. Worse, if you ask it
about those things anyway, it will often produce a confident, plausible-sounding, entirely
wrong answer — because it has **no mechanism to distinguish "I know this" from "this sounds
like the kind of thing that would be true."**

RAG fixes this **without retraining the model**. At the moment you ask a question, the system
retrieves the most relevant pieces of your own documents and hands them to the LLM as extra
context in the prompt. The model then answers by **reading** rather than **recalling**.

### Two distinct phases

**Indexing** — done once, offline, whenever documents change:
1. **Documents** — the raw text the system should know about.
2. **Chunking** — split each document into small, coherent pieces.
3. **Embedding** — convert each chunk into a vector representing its meaning.
4. **Vector store** — save the vectors (plus the original text) in a database built for
   "find the closest vectors to this one" search.

**Query** — runs every time a question is asked:
1. **Embed the question** using the *same* embedding model.
2. **Retrieve** the top-k nearest chunks.
3. **Augment the prompt** — insert the chunks alongside the question.
4. **Generate** — the LLM produces an answer grounded in the retrieved text.

> **The core insight:** the "augmented" in Retrieval-Augmented Generation means augmenting
> *the prompt*, not augmenting the model. Mechanically, RAG is string concatenation plus a
> good search step.

---

## 2. Tokens — foundational vocabulary

LLMs don't process text as letters or whole words. Text is first chopped into **tokens** —
usually a common word, a fragment of a longer word, or punctuation.

Rough English rule of thumb: **1 token ≈ 4 characters ≈ ¾ of a word.** So 100 words ≈ 130–150
tokens.

Example — "I am learning retrieval augmentation" becomes about 8 tokens:

| I | am | learning | retri | eval | augm | ent | ation |
|---|---|---|---|---|---|---|---|

Common words get one token each; rarer or longer words split into fragments. This is how models
handle words they've never seen — they assemble them from known pieces.

---

## 3. How generation actually works

**One forward pass per generated token.** The model takes everything seen so far, computes a
probability distribution over its entire vocabulary for what comes next, picks one, appends it,
and runs again on the now-longer sequence. This is **autoregressive** generation.

A 200-token answer means 200 separate passes. Token 50 cannot exist before token 49, because
token 49 is part of the input that determines token 50. **This is why generation can't be
parallelized** the way training can.

**The KV cache** is the optimization that keeps this tractable. Naively, pass 50 would redo all
the work for tokens 1–49. Instead, models cache intermediate attention results, so each new
pass only computes the genuinely new work for the newest token.

### Two phases, visible in practice

- **Prefill** — processing the input prompt. All tokens are already known, so they're pushed
  through in parallel. **Fast.**
- **Decode** — generating the response, one token at a time. **Slow.**

This is why chatbots pause after you hit enter (prefill), then drip out text (decode).

> **Why this matters for RAG:** retrieval stuffs a lot of extra text into the prompt. Those
> extra tokens go through prefill, which is parallelizable and relatively cheap. Meanwhile the
> answer is decoded sequentially. So **retrieving more context costs far less than you'd guess,
> while a longer answer costs proportionally more.**

---

## 4. Running a model locally — the Ollama idea

Open-weight models ship as raw files: gigabytes of numerical weights. Running one manually
means dealing with file formats, inference engines, GPU offload configuration, and matching
CUDA versions. Tedious enough to be a real barrier.

Ollama wraps all of that behind a package-manager interface, and the useful mental model is
**Ollama is Docker for models**: a registry you pull from, `model:tag` naming, local storage of
pulled artifacts, and a runtime that hides environment details.

**The architectural point that matters:** Ollama runs a **server** in the background. Any
application talks to it over ordinary HTTP — structurally identical to calling a cloud LLM API,
except nothing leaves the machine. So a local model substitutes cleanly for a cloud API key,
and the same pipeline code works against either with only a URL change.

**Quantization** is why this fits on consumer hardware. A 3-billion-parameter model at full
precision would be ~12GB. Quantized versions store weights at reduced numerical precision
(commonly 4-bit instead of 16-bit), shrinking it to ~2GB. Small quality loss, huge practicality
gain.

**Honest tradeoff:** a small local model is meaningfully weaker than a frontier model — shorter
reasoning, more mistakes, weaker instruction-following. For *learning* RAG this is arguably
useful: a weaker model makes retrieval quality more visible, because bad context produces
obviously broken answers rather than being rescued by the model's own knowledge.

---

## 5. Chunking

### Why not embed whole documents?

An embedding compresses text into a **single fixed-size vector** — the same size whether the
input is one sentence or fifty pages. The longer the text, the more meaning gets averaged
together. A document covering OAuth, transport mechanics, and a startup bug produces one vector
sitting at the meaningless average of all three — close to a question about none of them.

### Why not one sentence per chunk?

Each vector is sharply focused, but individual sentences are often incomprehensible alone.
"That fixed it" tells the model nothing without its surrounding paragraph.

### So chunking is a tradeoff

| | Too small | Middle ground | Too large |
|---|---|---|---|
| Size | One sentence | A few paragraphs | Whole document |
| Meaning | Sharp | One clear topic | Averaged away |
| Context | None | Enough to stand alone | Plenty |

A typical starting point is several hundred to a thousand characters per chunk, with 10–20%
overlap.

### Overlap — why it exists

With strict fixed boundaries, some idea will land exactly across a cut — the setup in one
chunk, the conclusion in the next — and neither chunk answers the question properly. Overlap
repeats the tail of the previous chunk, so boundary-straddling ideas survive intact somewhere.
The cost is duplicated storage, which is cheap.

### Splitting strategies, in increasing order of sense

1. **Fixed-size** — cut every N characters. Trivially simple; slices words and sentences in half.
2. **Recursive character splitting** — the standard approach. Give it a priority list of
   separators: paragraph breaks, then line breaks, then sentence ends, then spaces. It tries
   paragraph boundaries first; if a piece is still too large, it recurses to the next separator
   down. Chunks respect natural structure wherever possible, breaking mid-sentence only as a
   last resort.
3. **Structure-aware** — split on the document's own semantics. For markdown, split on headers,
   so each chunk is a coherent section and can carry its heading as metadata.

### A concrete example

Original paragraph:

> The MCP server communicates with Claude Desktop over stdio transport. This means the server
> reads JSON-RPC messages from standard input and writes responses to standard output. There is
> no HTTP server involved. I initially tried to log debug output with print statements, which
> corrupted the message stream because stdout is reserved for protocol messages. Switching to
> stderr fixed it.

**Fixed-size splitting** cuts blindly — the word "server" gets sliced into "HTTP se" and "rver
involved". Both resulting vectors are polluted by the fragments.

**Recursive splitting** stops at a sentence boundary instead, ending a chunk slightly short of
the size limit rather than mid-word.

**Why overlap matters here:** the second chunk would open with "There is no HTTP server
involved" — but *what* has no HTTP server? The subject was named in the previous chunk.
Retrieved alone, it's an orphaned statement. Overlap carries the previous sentence forward so
the chunk can stand on its own.

> **The key insight: retrieval quality is bounded by chunking.** If the answer to a question is
> split across two chunks and only one is retrieved, no amount of LLM quality recovers it.
> People reach for bigger models when their real problem is that their chunks are wrong.

### A real complication worth knowing

Size-based chunking assumes adjacent text is topically continuous. That's true for prose. It's
**false** for a cheat-sheet of dense, self-contained one-liner bullets — there, unrelated facts
land in the same chunk purely because they were adjacent and fit within the size limit. The
resulting vector sits at the average of several topics and matches none of them squarely.

Overlap can also silently stop working: if a natural unit (like a long bullet) exceeds the
overlap window, an implementation may snap to a separator boundary and drop the overlap
entirely. Worth verifying rather than assuming it's uniform.

---

## 6. Vector databases, and why pgvector

Regular databases find rows by exact match. Retrieval needs a different question answered:
*"which stored vectors are geometrically closest to this one?"* That's nearest-neighbour
search — a different indexing problem, hence a whole category of vector databases.

**pgvector is not a separate database** — it's a **Postgres extension**. Postgres's plugin
system lets extensions add new column types, operators, and index types to the core engine.
pgvector adds a vector column type, distance operators, and index types that make
nearest-neighbour search fast at scale.

So chunks live in an ordinary table, and retrieval is plain SQL that orders rows by distance
from the query vector and takes the top few.

**Cosine distance is the usual choice for text** because it compares vector *direction* rather
than magnitude — two chunks on the same topic point the same way regardless of how long they
are.

### Why "just use Postgres" is a strong production argument

If the application already runs Postgres, there's no new database to operate, back up, secure,
or pay for. Vectors sit in the same transaction as application rows — you can join against real
tables, filter before the vector search, and get ACID guarantees for free. Dedicated vector
databases win at very large scale, but "just use Postgres" covers a surprising number of real
systems.

### Approximate nearest neighbour

Exact nearest-neighbour search over millions of vectors is too slow, so vector databases use
**approximate** algorithms — HNSW (Hierarchical Navigable Small World) is the common one —
trading a little recall for a large speed win.

---

## 7. Embeddings

### What the numbers are

**Coordinates.** A point in high-dimensional space.

Two numbers locate a point on a grid; three locate a point in a room. There's no reason to stop
at three except that we can't picture more. A 768-number embedding locates a point in a space
with 768 axes. Distance, direction, and closeness all work identically — only visualization is
lost.

Common dimension counts are 384, 768, 1024, 1536. More dimensions means more capacity for fine
distinctions, but bigger storage and slower search.

**The dimensions are not individually meaningful.** There's no "formality axis" or
"is-about-databases axis." You cannot inspect dimension 412 and say what it encodes. The meaning
lives in the **overall arrangement** — which points end up near which other points.

### How they're formed

An embedding model is a neural network: text in, numbers out. The training idea is
**contrastive**: show it pairs of text that should be related, and pairs that shouldn't, then
adjust it until related pairs land close together and unrelated pairs land far apart.

The pairs come from structure already present in scraped data — a question and its accepted
answer, a title and its article body, two consecutive sentences, a summary and its source.

The model starts producing essentially random vectors. Shown a related pair, it measures how far
apart it placed them and nudges its weights to pull them closer; shown an unrelated pair, it
nudges the other way. One update changes almost nothing. Hundreds of millions of them, and the
geometry settles into a usable map.

**Nobody defines what "similar" means.** It's learned entirely from the statistical structure of
how humans actually use language.

### The distance logic

Cosine distance measures the **angle** between two vectors, not the straight-line gap between
the points.

| Angle | Distance | Meaning |
|---|---|---|
| 0° — same direction | 0 | same meaning |
| 90° — perpendicular | 1 | unrelated |
| 180° — opposite | 2 | opposing meaning |

**Why angle rather than straight-line distance?** Magnitude tends to track things you don't care
about — mainly text length. A long paragraph and a short sentence saying the same thing produce
vectors of different lengths pointing in nearly the same direction. Cosine discards the length
and keeps the direction, which is where the meaning is.

**In practice the range is compressed.** Real distances mostly fall between roughly 0.15 and
0.7 — nothing near 0, nothing near 1. So "close" is relative to the model's actual distribution,
not the abstract scale.

### What a query and a matching chunk actually have in common

**Lexically, possibly nothing. That's the entire point.**

- Question: *"Why did my debug logging break the MCP server?"*
- Matching chunk: *"I tried logging debug output with print statements, which corrupted the
  message stream because stdout is reserved for protocol messages."*

Shared words: "logging" and "debug". That's it. "Break" doesn't appear in the chunk;
"corrupted", "print statements", and "stdout" don't appear in the question. **A keyword search
would score this weakly.**

What they share is **the same region of learned meaning-space**.

---

## 8. Building the intuition

### The underlying principle

*You shall know a word by the company it keeps.* A word's meaning is captured by which words
tend to surround it.

**Self-test.** You've never seen the word "flurgle", but:

> I flurgled the milk before pouring it.
> Don't flurgle the leftovers too long or they'll spoil.
> She flurgled the wine to check if it had turned.

You now know roughly what it means — smell or taste to check freshness. Nobody defined it. You
inferred it purely from the contexts it appeared in. **Embedding training automates exactly this
inference, at enormous scale.**

### Why "broke" and "corrupted" converge

These all appear in vast numbers across scraped text:

> The update **broke** my build.
> The update **corrupted** my build.
> The update **destroyed** my build.
> The update **messed up** my build.

Identical surroundings, different word in the slot. **Substitutability is the signal.** Words
that fit the same holes get placed near each other.

Same mechanism for "print statements" and "debug logging" — both appear constantly in frames
like "I added ___ to see what was happening."

Nobody wrote a thesaurus. The pattern is a statistical residue of how people actually write.

### The famous demonstration

Take the vector for "king", subtract "man", add "woman" — and the closest result is "queen."

This works because gender-related meaning occupies a consistent **direction** in the space. The
same direction connects uncle→aunt, actor→actress, father→mother. The model was never taught
what gender is; it emerged because gendered pairs appear in systematically parallel contexts.

**Relationships are encoded as directions** — the space has real structure, not just clumps.

### The map analogy

Imagine being handed millions of city-pair distances with no names and no coordinates: "A to B
is 300km, B to C is 150km." You could reconstruct a map — not knowing what any city *is*, but
placing them all consistently with every distance given. Cities always mutually close would form
a cluster you might later recognize as a country.

Embedding training is that, where "distance" means "how often these appear in related contexts."

---

## 9. Where embeddings break down

### Antonyms and negation

**Substitutability is not the same as similarity.**

> The service is **up**.
> The service is **down**.

These appear in nearly identical contexts constantly, so they land **close together**. In
testing, this pair came out as by far the *closest* of any pair measured — roughly three times
closer than two sentences that were genuinely about the same bug.

**Practical consequence:** asking *"which approaches did NOT work?"* will happily return chunks
about approaches that *did* work. When evaluating retrieval, remember that a wrong result isn't
always a bug in your code.

### Exact identifiers

Embeddings are bad at error codes, version numbers, SKUs, and precise names. "What does error
code E4021 mean?" is nearly hopeless semantically — that code is a meaningless token with no
learned associations.

This is why production systems use **hybrid search**: semantic search for meaning, plus keyword
search (BM25) for exact terms, with results merged.

### Weak discrimination within a domain

A subtle and important one. Within a single technical domain, distances between genuinely
related and genuinely unrelated chunks can be nearly identical. Retrieval works by *ranking*, so
a hair's difference is technically enough — but it means ranking is **fragile**. Small phrasing
changes can reshuffle results arbitrarily, and near-misses can crowd out the right answer.

---

## 10. Does the model decide when to retrieve? No.

A common misconception worth killing early: **in basic RAG, the model decides nothing.
Retrieval always happens, unconditionally.**

The model never sees the question in isolation, and is never asked "do you need help with this?"
By the time it's involved, the context is already in the prompt. From the model's point of view
there is no retrieval step — it just received an unusually long prompt that happens to contain
relevant reference material.

Consequence: ask "what is 2+2?" and the system still retrieves four chunks and pastes them in.
The model answers "4" and ignores them. Slightly wasteful, harmless.

### Systems that *do* decide — the next tier up

- **Routing** — a cheap classifier or quick model call inspects the question first and picks a
  path: retrieve from docs, query a database, web search, or answer directly. A separate
  decision step *before* retrieval.
- **Agentic RAG** — retrieval is exposed to the model as a **tool**, and the model chooses
  whether and when to call it. This is exactly the MCP mechanism: the model gets a tool schema,
  decides to invoke a search, reads the results, and can search again with a refined query if
  the first attempt was unhelpful. Multiple model-driven retrieval rounds.

Agentic RAG is this same pipeline with a decision layer wrapped around it — which is why it only
makes sense to build after the unconditional version works.

---

## 11. What gets stored

Each row holds a chunk twice, in effect: once as human-readable text, once as machine-comparable
geometry.

| Column | Purpose |
|---|---|
| **id** | Primary key |
| **content** | The chunk text. Stored because retrieval must hand *readable text* to the LLM — **an embedding cannot be reversed back into words.** |
| **metadata** | Source file, section header, position. Enables filtering and citations. |
| **embedding** | The vector. Fixed length, determined by the embedding model. |

**One subtlety:** some embedding models expect **task prefixes** — a marker distinguishing text
being indexed from text being used as a query, because the model learned an asymmetry between
those roles. When they're used, the prefix is an instruction to the *embedding model*, not part
of the document, so it must not be stored in the content column or it ends up as noise in the
prompt sent to the LLM.

---

## 12. The flow, in plain words

You ask: *"What was my test calendar named?"*

**Step 1 — Your question becomes numbers.**
The question is sent to the embedding model. Back come 768 numbers. That's your question turned
into a location on a map of meaning.

**Step 2 — The database finds the closest chunks.**
Those numbers go to Postgres, which is asked: *which few rows have numbers closest to these?* It
compares against every stored chunk and returns the nearest handful. This takes milliseconds. No
AI involved — just math over a table.

**Step 3 — Everything is glued into one text block.**
The retrieved chunks and your question are concatenated into a single string:

> Use only the following context to answer the question.
> If the context does not contain the answer, say you don't know.
>
> Context:
> [chunk 1 text]
> [chunk 2 text]
> [chunk 3 text]
> [chunk 4 text]
>
> Question: What was my test calendar named?

**Step 4 — That block goes to the LLM.**
The model reads it and writes an answer.

**Step 5 — The answer comes back.**

That's the whole thing. Five steps, **two model calls** (one to turn the question into numbers,
one to write the answer), **one database lookup** in between.

Note that the vectors never reach the LLM. They're purely the addressing mechanism — how you
*find* text. Once found, only text is sent.

---

## 13. Proving it actually works — the canary idea

### The problem with obvious tests

If your documents cover a topic the model already knows from training, a correct answer proves
nothing. The model might be answering from memory while retrieval silently does nothing.

Asking "what is stdio transport?" could be answered either way. Asking "what transport did *I*
use in *my* project?" can only be answered by retrieval.

### The canary technique

Plant a fact in the source document that is **impossible to know otherwise** — an invented name
that exists nowhere else in the world. If the system answers a question about it correctly,
that's unambiguous proof retrieval is feeding real context into the prompt. No other explanation
is available.

### The result

A made-up calendar name was planted in the notes before indexing.

**With retrieval:** the system returned the correct invented name.

**With retrieval disabled** (bare question sent straight to the model): the model said it had no
information about any test calendar and couldn't help.

**This is unambiguous proof that the pipeline genuinely grounds answers in the indexed
documents.** The correct answer could only have come from the retrieved chunk.

Also worth noting: with no context, the model *correctly admitted ignorance* rather than
inventing a plausible calendar name. That's the desirable behaviour, and it doesn't always
happen.

---

## 14. Lessons from actually building it

### Two failures that look identical from the outside

A wrong answer can come from **retrieval** (the right chunk was never fetched) or from
**generation** (the right chunk was fetched and the model ignored or misread it). These need
completely different fixes, and telling them apart is the core debugging skill.

**This is why you print the retrieved chunks and their distances before generating.** Without
that, every failure looks the same.

One real example: a question returned a confidently wrong answer. Inspection showed none of the
retrieved chunks contained the relevant fact — even though the fact was definitely in the
database. That's a *retrieval* failure. **And separately**, the prompt had instructed the model
to say "I don't know" when the context lacked the answer, and it invented an answer anyway.
That's a *generation* failure. Two independent problems in one wrong answer.

> **A grounding instruction is only as good as the model's willingness to follow it.** Small
> models follow instructions weakly.

### Diagnosing a retrieval failure

Two questions, in order:

1. **Is the content even in the database?** A simple text search answers this. If it's missing,
   the bug is in indexing, not retrieval — a completely different investigation.
2. **Where does it rank?** Retrieve many more results than usual and see where the correct chunk
   lands. Position 6 or 7 means retrieval nearly works and k is just too small. Absent from
   twenty means the embedding genuinely isn't matching.

### Retrieval can be inconsistent rather than broken

The same system failed on one question and succeeded on another. That distinction matters: a
*broken* system (mismatched embedding spaces, corrupted index) fails uniformly. Inconsistent
failure points at ranking and question phrasing, not configuration.

### Multi-concept questions get averaged

A question containing two concepts produces one vector sitting between them. The more
distinctive concept can dominate and pull results toward itself — especially if it matches
something literal, like a filename. The question was about a *concept*; the retrieval went to
chunks named after a *file*.

### Small hand-picked tests can't evaluate retrieval

An attempt to validate embedding behaviour on three chosen sentences produced a misleading
result — because the labels "related" and "unrelated" reflected human knowledge of the project's
causal story, not surface meaning. The model saw two structurally parallel sentences and judged
them similar, which wasn't unreasonable.

> **Real evaluation is end-to-end: real chunks, real questions, does the right thing come back.**
> A test whose answer depends on your own judgment of what "related" means isn't measuring the
> model.

### Don't fix unmeasured problems

Several potential issues were spotted early — inconsistent overlap, mixed-topic chunks, very
small chunks. All were deliberately left alone until they could be *observed* causing failures.
Two rounds of tuning were spent on a problem that turned out not to be the real one.

---

## 15. How organizations deploy this for real

Same pipeline. What changes is everything around it — plus one component with no equivalent in a
learning project.

**The LLM is usually managed, not self-hosted** — cloud providers under enterprise agreements
where the vendor contractually doesn't train on the data. Note the data-residency asymmetry: the
*documents* stay in your own vector store; only the retrieved chunks for a given question
transit to the model.

**Ingestion becomes the hard part.** Not one file, but wikis, drives, ticket systems, and chat
archives, all changing continuously. That means scheduled or webhook-driven sync, change
detection so only modified documents get re-embedded, format extraction for every file type, and
handling for documents that fail to parse. Usually most of the engineering effort and none of
the interesting part.

### Access control — the piece that gets people fired

The vector store holds chunks from documents with wildly different permissions. If retrieval
ignores that, someone asks an innocent question and receives a chunk from the compensation
spreadsheet. **There is no clawing that back.**

The correct approach is **pre-filtering**: store each chunk's access list as metadata and filter
*before* the vector search, so unauthorized chunks never enter the candidate set. This is the
strongest argument for putting vectors in a relational database — you get real filtering and
joins against identity tables in the same query.

**Permission drift** is the nasty version: someone's access is revoked, but the index still
reflects the old permissions until the next sync. Serious systems re-check against the live
source at query time rather than trusting indexed metadata.

### Retrieval gets more sophisticated

- **Hybrid search** — semantic plus keyword, results merged, because of the exact-identifier
  weakness.
- **Reranking** — retrieve many candidates cheaply, then run a **cross-encoder** over them to
  score relevance properly and keep the best few. Cross-encoders read the query and chunk
  *together* rather than comparing two independently-computed vectors, so they're much more
  accurate and far too slow to run over a whole corpus. **Retrieve-wide-then-rerank is the
  standard pattern.**

### Evaluation separates working systems from demos

A golden set of questions with known-correct answers, run on every change to chunking,
embeddings, or prompts. Without it you're guessing whether a change helped — the same reason the
canary test matters at small scale.

### The operational layer

Citations back to source documents (users don't trust uncited answers, and it makes
hallucinations checkable) · logging of retrieved chunks per query for debugging complaints ·
feedback collection · cost controls · PII handling in logs.

### Many companies buy rather than build

The connectors-and-permissions problem is tedious and not differentiating, so paying for a
managed product is often the correct call.

> **For system design interviews:** the permissions model is the piece worth being able to
> discuss unprompted. It distinguishes someone who has read about RAG from someone who has
> thought about deploying it.

---

## 16. Ideas worth exploring next

- **Hybrid search** — add keyword matching alongside semantic, and see whether it rescues the
  questions that semantic search alone gets wrong.
- **Reranking** — retrieve widely, then score properly.
- **Tuning k** — fewer chunks means less noise and faster generation; more chunks means better
  recall. There's a real tradeoff to feel out.
- **Chunk strategy experiments** — merging very small chunks into neighbours, and splitting
  mixed-topic chunks more aggressively.
- **A proper evaluation set** — a handful of questions with known answers, so changes can be
  measured rather than guessed at.
- **Agentic RAG** — expose retrieval as a tool and let the model decide when and what to search.
  This is where RAG and MCP converge.
