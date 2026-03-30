# Contributing to VideoTool

Thanks for your interest in contributing!

## Getting Started

1. Fork the repo and clone it locally
2. Run `scripts/dev.sh` to set up the Python environment
3. Run `npm install` for the frontend dependencies
4. Copy `.env.example` to `.env` and fill in your API keys

## Development

- Python CLI: `src/videotool/`
- Tauri app: `src-tauri/`
- Svelte frontend: `src-svelte/`
- Cloudflare Worker: `cloudflare-worker/`

## Testing

```bash
pytest
```

## Pull Requests

- Keep PRs focused on a single change
- Include tests for new functionality
- Update README.md if you change CLI commands or options

## Reporting Issues

Open an issue on GitHub with steps to reproduce.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
