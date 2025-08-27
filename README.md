# Figpack URL References

This repository maintains a regularly updated index of Figpack figure URLs used across public GitHub repositories. It helps track and discover where Figpack figures are being referenced in Markdown documentation.

## How it Works

The repository uses a GitHub Actions workflow to:

1. Search public GitHub repositories for Markdown files containing Figpack URLs (`https://figures.figpack.org/`)
2. Clone repositories and scan their Markdown files for Figpack references
3. Generate a JSON file containing all found references
4. Deploy the results to GitHub Pages

The data is updated daily and on each push to the main branch. You can also trigger the update manually from the Actions tab.

## Accessing the Data

The data is available in two formats:

1. **Web Interface**: Visit our [GitHub Pages site](https://[username].github.io/[repository-name]/) for a user-friendly view
2. **JSON API**: Access the raw data at `https://[username].github.io/[repository-name]/figpack-url-refs.json`

The JSON data structure:

```json
[
  {
    "repo": "owner/name",
    "file": "relative/path/to/file.md",
    "url": "https://figures.figpack.org/..."
  }
]
```

## Local Development

### Prerequisites

- Python 3.x
- Git
- GitHub Personal Access Token (for higher API rate limits)

### Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/[username]/[repository-name].git
   cd [repository-name]
   ```

2. Install dependencies:

   ```bash
   pip install requests
   ```

3. Run the script:
   ```bash
   python find_figpack_urls.py
   ```

Optional environment variables:

- `GITHUB_TOKEN`: GitHub Personal Access Token for higher API rate limits

### Script Options

```bash
python find_figpack_urls.py [options]

Options:
  --out        Output JSON file path (default: figpack-url-refs.json)
  --workdir    Working directory to clone repositories (default: ./_repos)
  --max-pages  Max pages to fetch from GitHub code search (default: 10)
  --per-page   Items per search page, max 100 (default: 100)
  --max-workers Number of parallel workers for cloning/scanning (default: 8)
```

## License

MIT
