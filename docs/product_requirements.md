# Product Requirements

QuickInsight Desktop follows the contract in `AGENTS.md`.

## P0 Goal

Provide an offline Windows desktop workflow:

`import/paste -> confirm -> profile -> choose intent -> receive explainable recommendations -> generate/refine interactive charts -> save/export`

## M0 State

M0 only creates the foundation: repository structure, launchable Qt shell, theme tokens, paths/settings/logging, error/job primitives, samples, scripts, CI, and tests. It must not imply that import, profiling, charts, transforms, or project persistence are ready.

## User Language

The default UI language is Simplified Chinese. Engineering documentation and tests may use English.
