# 08 — Design notes

← [07 — Assemble and deploy](07-assemble-and-deploy.md)  ·  [Index](README.md) →

Why the constructs look the way they do. Each note is a decision you can carry
back to your own CDK codebase.

## Move shared state up, out of the thing that used it first

`TrustStore` is created in the stack and injected into `Gateway`, not created
inside `Gateway` and exposed as an attribute. It is not part of the API — it is
a *peer* the API and both services share.

**The rule:** when a second consumer appears for something a construct owns
privately, move it up to the nearest common scope. Do not add an accessor; that
makes the owner responsible for a lifecycle it does not control, and every
consumer then depends on the owner just to reach the dependency.

Practical consequence: logical ids come from the construct path, so moving a
construct in the tree *replaces* its resources on the next deploy. A pure
refactor is never free in CloudFormation.

## Pass the construct, not the string it produced

```python
FastApp(self, "FastApp", domain=..., trust_store=trust_store)   # not trust_store.uri
```

* `trust_store: TrustStore` accepts the one right thing; `truststore: str`
  accepts any string on earth.
* If `FastApp` later needs the bucket ARN too, it already has it — no second
  parameter, no breaking change to callers.
* CDK builds its ordering graph from construct references. A string carrying a
  token works, but a construct reference says it outright.
* Exactly one line knows the URI format, inside the service construct.

**The rule: constructs take constructs.** Reach for `.uri`, `.arn`, `.name` at
the last possible moment. Same instinct as `bucket.grant_read(fn)` over
hand-written ARNs.

## Delete flexibility nobody uses

`PyconZone` hard-codes its parent zone in three module constants. An earlier
version took a `ParentZone` dataclass — with one caller, one possible value, and
two of three fields already defaults nobody overrode. That is not configuration;
it is a parameter *shaped like* configuration, and it costs a dataclass and an
import at every call site, plus a docstring that must speak in generalities
instead of naming the actual system.

**The rule:** generality is a cost paid now for an option exercised later. Take
it out when the option is never exercised — and note how cheap it is to add back
for a real second case. Deleting an abstraction three teams already depend on is
not cheap at all.

## …but make optional what genuinely has two cases

`Gateway`'s `zone` and `trust_store` are both optional, so
`Gateway(self, "Gateway")` is a working API on its `execute-api` URL. That case
is real — a unit test, a scratch API, a stack with no zone to delegate.

The test distinguishing this from the note above is simply: **does the other
case exist?** And the optionality must be honest — each missing dependency
removes a feature rather than half-configuring one. An optional parameter that
leaves the construct broken is worse than a required one.

## Names that repeat their context

`pycon2026/stack.py`, class `Stack` — not `pycon2026_stack.py` /
`Pycon2026Stack`. The module path already carries the project name. `Stack` then
shadows `cdk.Stack`, which is why the file imports `aws_cdk as cdk` and
subclasses `cdk.Stack` — a small price, paid once.

The stack's *construct id* is still `"Pycon2026Stack"`. That id is the
CloudFormation stack name; changing it would orphan the deployed stack. Rename
Python freely; think hard before renaming construct ids.

## Comments that record why, not what

Two comments in this repo earn their place: the paragraph in `cdk_pipeline.py`
explaining why tag values are hashed and base64-encoded, and the note in
`gateway.py` explaining why the API is `REGIONAL`. Both record a decision and
its constraint — information nowhere in the code, that the next person would
otherwise "simplify" away.

## Review checklist

- [ ] Does the stack file read as a wiring diagram, or does it declare resources?
- [ ] Does every construct take **constructs** rather than the strings they produce?
- [ ] Is anything created inside a construct that a second consumer now needs?
- [ ] Does every parameter have at least two real values across the codebase?
- [ ] Does every optional parameter leave the construct **working** when omitted?
- [ ] Are open-ended collections added by a method (`add_*`) rather than a list
      parameter?
- [ ] Are permissions written with `grant_*` rather than hand-rolled policies?
- [ ] Would renaming this construct move a logical id — and have you checked what
      that replaces on the next deploy?

## Where to go next

* **Multiple environments.** One `Stack` per environment in
  [app.py](https://github.com/czarny/pycon2026/blob/main/app.py), with different `env=` and `record_name=`.
* **Tests with real assertions.** [tests/unit/test_stack.py](https://github.com/czarny/pycon2026/blob/main/tests/unit/test_stack.py)
  synthesizes and asserts nothing. `assertions.Template` has
  `has_resource_properties`, `resource_count_is` and `find_resources` — assert
  the mTLS wiring so it cannot silently regress.
* **`cdk.Aspects`** to enforce the checklist mechanically.
* **Publish your constructs.** `TrustStore` and `CdkPipeline` are useful beyond
  this repo.

---

← [07 — Assemble and deploy](07-assemble-and-deploy.md)  ·  [Index](README.md) →
