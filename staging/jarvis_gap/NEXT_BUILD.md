# Next Jarvis build slice — staging only

This extends the existing gap package without changing production Aletheia.
Nothing here is registered, routed by the Core, imported by `aletheia/`, or able
to execute an action.

## 1. Richer computer actions — contract, not executor

`computer_extensions.py` adds proposal contracts for the missing interaction
primitives that do not exist in production `aletheia.computer` today:

- semantic scroll;
- bounded hotkeys;
- semantic drag/drop;
- clipboard write;
- file-picker selection.

The contract deliberately does **not** implement them. Every proposal carries
`execution_authority: false`, a canonical sha256, and the highest risk of any
step. Drag/drop stays semantic: x/y coordinates are refused. Visual targeting
remains a separate lower-priority fallback and may never silently become the
normal path.

Before integration Claude should decide, action by action, which production
backend mechanism is reliable and how success will be re-observed. A hotkey
being emitted is not evidence its intended effect happened.

## 2. Browser/file transfers — exact artifact binding

`browser_transfers.py` adds proposal contracts for upload/download work without
opening a browser.

Uploads:

- must be inside explicitly allowed roots;
- must be a regular file rather than an arbitrary path;
- are byte-bounded;
- are bound to filename + size + sha256;
- do not expose the local path in diagnostic metadata.

Downloads:

- must land inside an explicitly allowed root;
- use a simple basename only;
- require a byte ceiling and expected HTTP(S) origin;
- refuse overwrite;
- do not expose the destination path in diagnostic metadata.

Production integration must still verify the resulting downloaded file rather
than treating a browser event as completion.

## 3. Multimodal routing — no silent downgrade

`multimodal_router.py` defines only three stable reasoning roles: `fast`, `deep`
and `vision`. It does not call models, plan tools, or execute anything.

The important invariant is that an image request requiring `vision` fails when
VISION is unavailable. It may not silently fall back to a text-only worker and
invent what was in the image. The same rule applies to an explicit deep request.
Safety-critical reasoning is marked non-authoritative even when a worker is
available; Aletheia's ordinary policy/verification layer remains the authority.

## Focused evidence

The new `tests/test_next_gaps.py` slice has 12 focused tests covering:

- semantic-only targeting and coordinate rejection;
- risk propagation and bounded hotkeys;
- upload hash binding and allowed-root enforcement;
- download traversal/overwrite refusal;
- VISION-required routing and no silent modality downgrade;
- non-authoritative safety-critical reasoning.

ChatGPT ran those 12 tests successfully in an isolated local staging harness
before committing this slice. The repository's normal PR CI does not discover
`staging/jarvis_gap/tests`, so Claude should explicitly run the full staging
suite during review.

## Still intentionally not built

- no scroll/hotkey/drag/clipboard/file-picker executor;
- no browser upload/download executor;
- no coordinate click bridge;
- no VISION model default;
- no Core routes or command kinds;
- no capability registry changes;
- no change to approval policy or standing authority.

That is intentional. This slice makes the eventual production implementation
reviewable before it makes Aletheia more powerful.
