# Development Setup

This guide explains how to test changes from a branch without publishing to the marketplace.

## Prerequisites

- [Claude Code](https://claude.ai/code) installed
- Your branch pushed to GitHub

## Install from a branch

Remove any existing installation, then add the marketplace pointing to your branch:

```
/plugin uninstall autonoma-test-planner-development
/plugin marketplace remove autonoma
/plugin marketplace add https://github.com/Autonoma-AI/test-planner-plugin#your-branch-name
/plugin install autonoma-test-planner-development@autonoma
```

## Updating after changes

Push new commits to your branch, then reinstall:

```
/plugin uninstall autonoma-test-planner-development
/plugin marketplace remove autonoma
/plugin marketplace add https://github.com/Autonoma-AI/test-planner-plugin#your-branch-name
/plugin install autonoma-test-planner-development@autonoma
```

## Environment variables

The plugin requires three environment variables to be set in the project where you run it:

| Variable | Description |
| --- | --- |
| `AUTONOMA_API_KEY` | Your Autonoma API key (get it from the dashboard under Settings > API Keys) |
| `AUTONOMA_PROJECT_ID` | The application ID from the Autonoma dashboard |
| `AUTONOMA_API_URL` | API base URL - use `http://localhost:4000` for local dev |

Add them to the `.env` file or export them in your shell before running Claude Code in the target project.

## References

- [Claude Code — Discover and install plugins](https://code.claude.com/docs/en/discover-plugins#add-from-github)
