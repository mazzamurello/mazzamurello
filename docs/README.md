# Documentation

Documentation follows the [Diátaxis](https://diataxis.fr/) framework. Today
only the development documentation exists; user documentation will be
written as features land, in the same pull requests flow (`docs/*`).

| Kind | Purpose | Location (planned) |
|---|---|---|
| Tutorials | Learning by doing: the first installation, the first conversation | `docs/tutorials/` |
| How-to guides | Solving a specific task: backups, reverse proxy, adding a model | `docs/how-to/` |
| Reference | Exact descriptions: configuration, API, CLI | `docs/reference/` |
| Explanation | Understanding: architecture, security model | `docs/explanation/` |
| Development | How the project is built | [`docs/development/`](development/) |

The specifications in [`specs/`](../specs/) are also public documentation:
the requirements say what the system does, the ADRs explain why, and the
[threat model](../specs/threat-model.md) describes the security model.
