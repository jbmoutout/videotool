# Project Rules

## Git Commits

When I ask to "commit" changes:
- Group changes into **atomic commits by logical topic/feature**, not one commit per file
- Each commit should represent a coherent change (e.g., "add feature X", "fix bug Y", "refactor Z")
- Related files that are part of the same feature/fix go in the same commit
- Push to the current branch after committing

## Documentation

- Always update README.md when adding/changing CLI commands, options, or user-facing features
- Keep README examples and command documentation in sync with the code

## Design System
Always read DESIGN.md before making any visual or UI decisions.
All font choices, colors, spacing, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match DESIGN.md.
