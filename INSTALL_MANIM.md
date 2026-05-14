# Manim Install — McNeillium_AI

The Illustration Engineer prefers real Manim over the PIL fallback because Manim's eased animations look noticeably better.

## What's installed today (working setup)

```
C:\Python314\python.exe         ← main project Python (3.14.3)
C:\Users\McNei\AppData\Local\Programs\Python\Python312\  ← installed by winget
venv_manim\Scripts\python.exe   ← Python 3.12 venv with manim 0.20.1
```

The Illustration Engineer auto-detects `venv_manim/Scripts/python.exe` and uses it for Manim CLI calls. Everything else stays on the project's 3.14 interpreter.

## How it got set up (record for posterity)

```powershell
# 1. Install Python 3.12 via winget (no admin required, user scope)
winget install --id Python.Python.3.12 --scope user --silent ^
    --accept-package-agreements --accept-source-agreements

# 2. Create a venv with Python 3.12 inside the repo
py -3.12 -m venv venv_manim

# 3. Install Manim into the venv
venv_manim\Scripts\python.exe -m pip install --upgrade pip manim
```

Result: `manim==0.20.1`, `moderngl==5.12.0`, `manimpango==0.6.1`, `pycairo==1.29.0`. All built from prebuilt wheels — no MSVC required.

## Why we needed this

Python 3.14 doesn't yet have prebuilt wheels for `moderngl` / `glcontext` (they need MSVC Build Tools to compile from source — a 15GB install). Python 3.12 has wheels for all Manim deps, so the simplest fix is to keep 3.12 around just for Manim rendering.

## LaTeX (MiKTeX) — still missing

`manim` itself works without LaTeX. Only the `MathTex` / `Tex` classes require it. Until MiKTeX is installed:

- Use `Text("E = mc^2")` (Unicode math) — works
- Avoid `MathTex(r"E = mc^2")` — fails
- The Animated Equation Renderer (Agent 55) uses PIL+Unicode for this exact reason.

To unlock LaTeX-quality equations later:

```powershell
winget install --id MiKTeX.MiKTeX --scope user --silent
```

## Sanity check

```powershell
venv_manim\Scripts\python.exe -c "import manim; print('manim', manim.__version__)"
# → manim 0.20.1

python -c "import sys; sys.path.insert(0, 'utils'); import illustration_engineer as ie; print(ie._manim_available(), ie._manim_python())"
# → True C:\...\venv_manim\Scripts\python.exe
```
