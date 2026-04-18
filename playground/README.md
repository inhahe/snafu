# Snafu Playground

A browser-based Snafu playground powered by [Pyodide](https://pyodide.org/) (CPython compiled to WebAssembly).

## Quick start

Serve from the repository root so the playground can fetch `snafu.py`:

```
cd snafulang
python -m http.server 8080
```

Then open `http://localhost:8080/playground/` in your browser.

## How it works

- Pyodide loads the full CPython runtime in the browser via WASM.
- On startup the playground fetches `../snafu.py` and executes it inside Pyodide, making all Snafu interpreter functions available.
- Clicking **Run** (or pressing **Ctrl+Enter**) calls `run(code)` inside Pyodide and captures stdout.
- The **Share** button encodes the current code into the URL hash so you can share a link.
- No server-side execution is needed; everything runs client-side.

## Requirements

- A modern browser (Chrome, Firefox, Edge, Safari).
- Internet access on first load (Pyodide is fetched from a CDN).
