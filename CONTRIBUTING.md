# Contributing to Crati.Co

*Διαβάστε αυτό σε άλλες γλώσσες: [English](CONTRIBUTING.md) | [Ελληνικά](CONTRIBUTING.el.md) (coming soon)*

Thank you for your interest in contributing to the Crati.Co platform! We welcome contributions of all kinds: code, documentation, bug reports, feature requests, and translations.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Features](#suggesting-features)
  - [Code Contributions](#code-contributions)
  - [Documentation](#documentation)
  - [Translations](#translations)
- [Development Setup](#development-setup)
- [Coding Standards](#coding-standards)
- [Commit Guidelines](#commit-guidelines)
- [Pull Request Process](#pull-request-process)

## Code of Conduct

This project adheres to a Code of Conduct that all contributors are expected to follow. Please be respectful, inclusive, and considerate in all interactions.

### Our Standards

- Using welcoming and inclusive language
- Being respectful of differing viewpoints and experiences
- Gracefully accepting constructive criticism
- Focusing on what is best for the community
- Showing empathy towards other community members

## How Can I Contribute?

### Reporting Bugs

Before submitting a bug report:
- Check the [existing issues](https://github.com/voulkon/crati/issues) to avoid duplicates
- Gather information about the bug (steps to reproduce, error messages, environment)

When creating a bug report, include:
- Clear and descriptive title
- Steps to reproduce the issue
- Expected behavior vs actual behavior
- Screenshots if applicable
- Environment details (OS, Docker version, etc.)
- Relevant logs or error messages

**Use the bug report template:**
```markdown
**Describe the bug**
A clear description of the bug.

**To Reproduce**
1. Go to '...'
2. Click on '...'
3. See error

**Expected behavior**
What you expected to happen.

**Environment:**
- OS: [e.g., Ubuntu 22.04]
- Docker version: [e.g., 20.10.17]
- Browser (if applicable): [e.g., Chrome 120]

**Additional context**
Any other relevant information.
```

### Suggesting Features

Before submitting a feature request:
- Check if the feature already exists
- Search existing feature requests
- Consider if it aligns with the project's goals

When creating a feature request, include:
- Clear and descriptive title
- Detailed description of the proposed feature
- Use cases and benefits
- Possible implementation approach (if you have ideas)
- Examples from similar projects (if applicable)

### Code Contributions

We love code contributions! Here's how to get started:

1. **Fork the repository**
2. **Create a feature branch** from `dev`
   ```bash
   git checkout -b feature/amazing-feature
   ```
3. **Make your changes** following our coding standards
4. **Test your changes** thoroughly
5. **Commit your changes** with clear commit messages
6. **Push to your fork**
7. **Open a Pull Request** to the `dev` branch

### Documentation

Documentation improvements are always welcome! This includes:
- Fixing typos or unclear explanations
- Adding examples or use cases
- Improving existing guides
- Creating new tutorials
- Adding diagrams or visualizations

**Documentation structure:**
```
docs/
├── en/               # English documentation
│   ├── ARCHITECTURE.md
│   ├── DEPLOYMENT.md
│   └── ...
└── el/               # Greek documentation (Ελληνικά)
    └── ...
```

### Translations

We're actively working on translating documentation to Greek (Ελληνικά). Contributions are highly appreciated!

#### Translation Guidelines

1. **Choose a document to translate**
   - Check the [translation status](docs/README.md#translation-status)
   - Priority: README → Quick Start → Deployment Guide

2. **Create or update the Greek version**
   - For main files: `README.el.md`, `CONTRIBUTING.el.md`
   - For docs: `docs/el/FILENAME.md`

3. **Translation standards**
   - Keep technical terms in English when commonly used (e.g., "Docker", "API")
   - Maintain the same structure as the original
   - Update code examples to include Greek comments where helpful
   - Preserve all links (they should point to English docs if Greek version doesn't exist)

4. **Mark translation status**
   - Add frontmatter or comment indicating translation date
   - Note the English version you translated from (commit hash is ideal)

#### Translation Workflow

```bash
# 1. Create a branch for translation
git checkout -b translate/greek-deployment-guide

# 2. Create the translated file
# For example: docs/el/DEPLOYMENT.md

# 3. Add translation metadata at the top
# Original: docs/en/DEPLOYMENT.md (commit: abc123)
# Translated on: 2026-03-05

# 4. Translate the content

# 5. Update docs/README.md to reflect new translation

# 6. Commit and push
git add docs/el/DEPLOYMENT.md docs/README.md
git commit -m "Add Greek translation of Deployment Guide"
git push origin translate/greek-deployment-guide

# 7. Open Pull Request
```

#### Translation Review

- Translations should be reviewed by at least one native speaker
- Technical accuracy is paramount
- Maintain consistent terminology throughout translations

## Development Setup

### Prerequisites

**Essential:**
- Docker 20.10+
- Docker Compose 2.0+
- Git

**Optional (for local development without Docker):**
- Python 3.11+
- Node 18+

### Quick Start

The simplest way to contribute is using Docker, which sets up everything you need:

1. **Clone the repository**
   ```bash
   git clone https://github.com/voulkon/crati.git
   cd crati
   ```

2. **Create environment file**
   ```bash
   cp .env_files/.env.local.secrets.example .env_files/.env.local.secrets
   # Edit the file if needed, but defaults work for development
   ```

3. **Start all services**
   ```bash
   docker-compose -f docker/docker-compose.yml --env-file=.env_files/.env.local.secrets up -d
   ```

4. **Run migrations**
   ```bash
   docker-compose exec backend python manage.py migrate
   ```

5. **Create superuser (optional)**
   ```bash
   docker-compose exec backend python manage.py createsuperuser
   ```

6. **Access the application**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - Admin panel: http://localhost:8000/admin

### Minimal Setup (Pocket Version)

For contributors focusing on specific features, you can run a minimal setup:

```bash
# Start only essential services
docker-compose -f docker/docker-compose.yml --env-file=.env_files/.env.local.secrets up backend db redis
```

This starts only the backend, database, and Redis - enough for API development and testing.

### Running Tests

```bash
# Backend tests
docker-compose exec backend pytest

# With coverage
docker-compose exec backend pytest --cov=api --cov=core

# Frontend tests
docker-compose exec frontend npm test
```

## Coding Standards

### Python (Backend)

- Follow [PEP 8](https://pep8.org/) style guide
- Use [Black](https://black.readthedocs.io/) for code formatting
- Use [isort](https://pycqa.github.io/isort/) for import sorting
- Add type hints where possible
- Write docstrings for classes and functions
- Maximum line length: 100 characters

**Example:**
```python
from typing import List, Optional

def process_document(document_id: int, force: bool = False) -> Optional[dict]:
    """
    Process a document by extracting text and indexing.

    Args:
        document_id: The ID of the document to process
        force: Whether to force reprocessing

    Returns:
        Dictionary with processing results, or None if failed
    """
    # Implementation
    pass
```

### JavaScript/React (Frontend)

- Use ES6+ syntax
- Follow [Airbnb JavaScript Style Guide](https://github.com/airbnb/javascript)
- Use [ESLint](https://eslint.org/) and [Prettier](https://prettier.io/)
- Use functional components with hooks
- Write PropTypes or TypeScript types
- Maximum line length: 100 characters

**Example:**
```javascript
import React from 'react';
import PropTypes from 'prop-types';

const DocumentCard = ({ document, onSelect }) => {
  return (
    <div className="document-card" onClick={() => onSelect(document.id)}>
      <h3>{document.title}</h3>
      <p>{document.summary}</p>
    </div>
  );
};

DocumentCard.propTypes = {
  document: PropTypes.object.isRequired,
  onSelect: PropTypes.func.isRequired,
};

export default DocumentCard;
```

### Docker & Configuration

- Keep Dockerfiles simple and well-commented
- Use multi-stage builds when appropriate
- Pin dependency versions
- Document environment variables

## Commit Guidelines

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification.

### Commit Message Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation changes
- **style**: Code style changes (formatting, missing semicolons, etc.)
- **refactor**: Code refactoring
- **perf**: Performance improvements
- **test**: Adding or updating tests
- **chore**: Maintenance tasks
- **ci**: CI/CD changes

### Examples

```bash
# Feature
git commit -m "feat(search): add semantic search with pgvector"

# Bug fix
git commit -m "fix(api): handle null values in document metadata"

# Documentation
git commit -m "docs(deployment): add multi-server setup guide"

# Translation
git commit -m "docs(i18n): add Greek translation of README"
```

## Workflow (Issue → Branch → PR → CI → Merge)

Every change follows this loop:

1. **Pick or open an issue** — all work starts from an issue. Use the issue templates (`.github/ISSUE_TEMPLATE/`). Assign yourself.
2. **Create a branch from `dev`**, named after the issue:
   ```bash
   git checkout dev && git pull origin dev
   git checkout -b feat/<issue#>-short-description
   ```
   Prefixes: `feat/`, `fix/`, `perf/`, `chore/`, `docs/`.
3. **Work in small commits** using conventional commit messages (`feat:`, `fix:`, `perf:`, `chore:`, `docs:`).
4. **Open a PR against `dev`** with the body referencing the issue (`Closes #<issue#>` — auto-closes it on merge).
5. **CI must pass** before merge. Two workflows run on backend changes:
   - **Backend CI** (`.github/workflows/ci.yml`) — fast tests without DB access (`pytest -m fast -k "not django_db"`)
   - **Database Tests** (`.github/workflows/db-ci.yml`) — fast tests requiring Postgres, runs on model/migration changes
6. **Merge to `dev`** (squash). The issue closes automatically.

Only after CI is green and the PR is merged can an issue be considered tackled.

## Pull Request Process

1. **Update your branch** with the latest `dev` branch
   ```bash
   git checkout dev
   git pull origin dev
   git checkout your-feature-branch
   git rebase dev
   ```

2. **Ensure all tests pass**
   ```bash
   pytest
   npm test
   ```

3. **Update documentation** if needed

4. **Fill out the PR template** completely

5. **Request review** from maintainers

6. **Address review comments** promptly

7. **Squash commits** if requested

### PR Title Format

Use the same format as commit messages:
```
feat(component): add new feature
fix(api): resolve bug in endpoint
docs(readme): improve installation instructions
```

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Translation
- [ ] Refactoring
- [ ] Other (please describe):

## Related Issues
Closes #123
Related to #456

## Testing
- [ ] All existing tests pass
- [ ] Added new tests
- [ ] Manual testing completed

## Screenshots (if applicable)

## Checklist
- [ ] Code follows project style guidelines
- [ ] Documentation updated
- [ ] Tests added/updated
- [ ] All tests pass
- [ ] Commit messages follow conventions
```

## Branch Strategy

- **`main`**: Production-ready code, stable releases
- **`dev`**: Development branch, integration happens here
- **`feature/*`**: New features
- **`fix/*`**: Bug fixes
- **`docs/*`**: Documentation updates
- **`translate/*`**: Translations

## Review Process

- PRs require at least one approval from a maintainer
- Translations require review from a native speaker
- Large changes may require multiple reviewers
- CI checks must pass before merging

## Recognition

Contributors will be recognized in:
- GitHub contributors list
- CONTRIBUTORS.md file
- Release notes (for significant contributions)

## Questions?

- Open a [GitHub Discussion](https://github.com/voulkon/crati/discussions)
- Contact maintainers directly

## License

By contributing, you agree that your contributions will be licensed under the GNU AGPL v3 License.

---

**Thank you for contributing to Crati.Co! 🎉**
