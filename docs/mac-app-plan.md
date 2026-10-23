# Story Guard Mac app

Status: the Mac app builds and runs. First launch installs a private Python, reuses Ollama and qwen3.5:4b when they are already on the Mac, and shows the PDF in the window. The personal access token is stored in a private file, and the progress percent is how many acceptance criteria have been reviewed.

A standalone macOS app that installs its runtime, connects to Azure DevOps, runs the existing local Qwen pipeline, and shows the PDF in the window.

## What the app does

1. On first launch, install anything that is missing: Python 3.13, the Story Guard package and its libraries, Ollama, and `qwen3.5:4b`.
2. Ask for an Azure DevOps personal access token and store it in a private file. The connect screen asks for the token only.
3. Let the user enter one story id, several story ids, or a sprint (an Azure DevOps iteration path).
4. Run a live generate with local Ollama.
5. Show a progress percent and the current step.
6. Open the finished PDF in the window, and save a copy wherever the user chooses.

The scoring, Azure DevOps reads, model prompts, and ReportLab layout stay in `src/story_guard`. The app does not reimplement them.

## Decisions

- Native SwiftUI app, bundle id `com.rootquotient.storyguard`, display name Story Guard. Xcode 26.3 and Swift 6.2 are already on this Mac. PDFKit displays the report.
- The app is not sandboxed. It has to download runtimes, start Ollama, and talk to `dev.azure.com`. It is ad-hoc signed so it launches locally. It is not notarized.
- Azure DevOps access is a personal access token. The organization and project stay `rootquotient` and `Ecom MVP`. The token needs Work Items Read and Test Management Read. It is stored in `~/Library/Application Support/Story Guard/ado-pat` with mode 0600 and passed only as `ADO_PAT` to the Python process. It is never written into the repo, into `.env`, or into a log.
- A sprint in this product is the iteration path `story-guard sprints` already prints, for example `Ecom MVP\Ecom phase 2.1 release\Story Guard - AI Agent`. The screen lists those paths and also accepts a pasted path.
- Generate in the app is always live. Fixture scoring stays on the CLI.
- The model installed by the app is `qwen3.5:4b` only. The 9B weights are too large for this 8 GB Mac, and `phi4-mini` stays the documented fallback, not something the installer pulls.
- If Ollama, the model, or a usable Python 3.12+ environment is already present, the installer skips that step.

## Layout

```
macos/
  StoryGuard.xcodeproj
  StoryGuard/
    StoryGuardApp.swift       # window, navigation
    SetupView.swift           # first-run checklist and percent
    ConnectView.swift         # token, how to create it, verify
    GenerateView.swift        # story / stories / sprint, Generate
    ReportView.swift          # PDFKit viewer, story picker, Download
    Installer.swift           # download, extract, venv, ollama pull
    Runner.swift              # spawn driver.py, stream JSON events
    TokenStore.swift          # private ado-pat file, mode 0600
    ProgressMath.swift        # percent from driver events
    Assets.xcassets
  driver.py                   # thin CLI bridge, no scoring logic
  driver_test.py              # progress-percent cases, no network
```

Runtime files live outside the repo:

`~/Library/Application Support/Story Guard/`

```
python/          # official CPython 3.13 install_only tarball (arm64)
venv/            # reportlab, langgraph, the local package on PYTHONPATH
engine/          # copy of src/, templates/, prompts/, fixtures/, pyproject.toml
ollama/          # Ollama.app only when /usr/local/bin/ollama is absent
artifacts/       # <story-id>.md and <story-id>.pdf
logs/            # installer and generate logs
ado-pat          # personal access token, mode 0600, never logged
```

`engine/` keeps the repo shape the code already uses. `graph.py`, `prefix.py`, and `envfile.py` resolve templates, the rubric, and fixtures through `Path(__file__).parents[2]`. With `PYTHONPATH=engine/src`, that parent is `engine/`, so templates and `prompts/rubric_v1.md` resolve. There is no `.env` in that folder, so the app's environment variables are what the process sees.

## First-run installer

`SetupView` runs the steps in order and shows one percent for the whole setup. Each step is skipped when its check passes.

| Step | Check | Action |
| --- | --- | --- |
| Python 3.13 | `python/bin/python3` runs and reports 3.13 | Download the pinned `cpython-3.13` `aarch64-apple-darwin` `install_only` tarball from python-build-standalone and extract it |
| Libraries | `venv` imports `reportlab` and `langgraph` | `python -m venv`, then pip install `reportlab` and `langgraph` from `pyproject.toml` pins. Copy `src`, `templates`, `prompts`, `fixtures` into `engine/` |
| Ollama | `GET http://127.0.0.1:11434/api/version` succeeds, or `ollama` is on `PATH` | Use the existing binary. Otherwise download `Ollama-darwin.zip`, put `Ollama.app` under Application Support, and start its `ollama serve` |
| Qwen | `ollama show qwen3.5:4b` succeeds | `ollama pull qwen3.5:4b`. Parse the pull percents into the setup bar |

The pinned Python release and the Ollama download URL are constants in `Installer.swift`, with a comment naming the version. Downloads show byte progress. A failed download can be retried. A partial extract is deleted before the retry.

Ollama is started only when nothing is listening on `11434`. The app does not install a launch daemon and does not ask for an admin password. This machine already has Ollama 0.34.4 at `/usr/local/bin/ollama`, so a normal launch here skips the Ollama download.

Each launch checks the runtime and repairs a missing model or a broken venv. Setup is not a toolbar button.

## Azure DevOps connection

`ConnectView` asks for the personal access token once. Organization stays `rootquotient` and project stays `Ecom MVP`. The screen lists the steps to create a token at `https://dev.azure.com/rootquotient/_usersSettings/tokens` and the mandatory scopes: Work Items Read, and Test Management Read.

The project URL is built as `https://dev.azure.com/{org}/{project}` with the project name percent-encoded. The same rules as `ADOClient`: HTTPS, no query, no fragment.

Verify runs `driver.py sprints` with those variables. Success stores the token in the private `ado-pat` file and stores the org, project, and URL in `UserDefaults`. Failure shows the driver error on the form.

A later launch reads that file and skips this screen when verify still succeeds. Connection in the toolbar returns to the form. Disconnect deletes the file.

## Generate screen

Three modes, one Generate button:

- One story. One numeric id.
- Several stories. Comma or newline separated numeric ids. Duplicates are dropped, order is kept.
- Sprint. A popup filled by `driver.py sprints`, plus a field for a pasted iteration path. The popup selection and the text field are the same value.

Generate stays disabled until setup is complete, the token is stored, and the input is valid. A story id must be a positive integer. A sprint value must be non-empty.

The run uses the Application Support venv and this environment:

- `ADO_PROJECT_URL`, `ADO_PAT`
- `STORY_GUARD_LLM=ollama`
- `OLLAMA_HOST=http://127.0.0.1:11434`
- `OLLAMA_MODEL=qwen3.5:4b`
- `STORY_GUARD_ARTIFACTS_DIR` pointing at the Application Support `artifacts/` directory
- `PYTHONPATH` pointing at `engine/src`

`keep_only_model` still runs inside the existing generate path, so a resident model other than `qwen3.5:4b` is unloaded before the first call.

## Driver

`macos/driver.py` is the only new Python entry. It calls `story_guard.cli.main` so the app and the CLI share one generate path.

Commands:

- `sprints` prints the iteration paths as JSON and exits with the CLI status.
- `generate --story-id 121213` repeats for each id, or `generate --sprint <path>`. It always passes `--live`.

While generate runs, the driver reads the CLI's stderr. Lines already look like `[story-guard] reviewing AC-01 against Suite (3/12, ...)`. The driver turns each line into one JSON object on stdout:

```json
{"event":"progress","story_index":1,"story_count":2,"message":"completed AC-03: 2 predicted test links","percent":12,"ac_completed":3,"ac_total":12}
{"event":"report","story_id":"121213","pdf":"/.../artifacts/121213.pdf","markdown":"/.../artifacts/121213.md"}
{"event":"error","story_id":"123086","message":"..."}
{"event":"done","written":["121213"],"failed":["123086"]}
```

Percent for a batch:

- `live review started: N acceptance criteria` sets the total. Until a criterion is completed, the story sits at 0.
- Each `completed AC-…:` line counts one acceptance criterion, once. The story percent is `completed * 100 / N`. Three of twelve is 25.
- The first fraction on a `reviewing` line is a suite batch inside the current criterion. It does not move the percent.
- `reports written` maps that story to 100.
- Overall percent is `((story_index - 1) * 100 + story_percent) / story_count`. Three of twelve on story 1 of 2 is 12.

A story that fails still advances the batch. The next story starts. The final `done` event carries both lists. The CLI already does this and exits 1 when any story fails. The driver exits with that same code.

`macos/driver_test.py` locks the percent math with a few captured stderr lines. It does not call Ollama or Azure DevOps.

## Progress and the PDF

During a run the generate screen shows:

- A progress bar and a whole-number percent.
- The current step sentence, for example `reviewing AC-03 against US - 123086 (2/8, ...)`.
- A disclosure that expands the full step log.

When a report event arrives, that story appears in a list. Selecting it loads the PDF in a `PDFView`. If the batch is still running, the first finished report opens and the bar stays visible.

Download opens `NSSavePanel`, defaulting to `~/Downloads/<story-id>.pdf`, and copies the file. The in-app file stays in Application Support. A Show in Finder button reveals it.

A failed story shows its error under the log. Stories that succeeded stay readable.

Cancel terminates the driver process group. A story that was mid-write may leave an unfinished PDF. The next Generate starts a new run. The existing engine already replaces the report only after a successful render.

## App flow

```
Launch
  -> runtime incomplete?  Setup
  -> no token, or verify fails?  Connect
  -> Generate
       -> run driver
       -> progress
       -> Report (PDF + Download)
```

The toolbar offers Connection so the token can be replaced. Setup runs when the app opens.

## Engine changes

None. The driver uses the public CLI. Artifact location is already `STORY_GUARD_ARTIFACTS_DIR` in `graph.artifacts_dir`.

## Build

The Xcode project is a single macOS app target, deployment target macOS 14, arm64. `driver.py` and `driver_test.py` are copied into the app Resources. Swift shells `Resources/driver.py` with the Application Support Python.

Build with `xcodebuild -project macos/StoryGuard.xcodeproj -scheme StoryGuard -configuration Debug`. The product is `StoryGuard.app`.

## How this will be checked

- `driver_test.py` against the app venv, or the project `.venv` if the app venv is not ready yet.
- `xcodebuild` succeeds.
- Launch the app. On this Mac, setup should detect the existing Ollama and `qwen3.5:4b` and only create the private Python venv.
- Walk Connect with an empty token and confirm Verify stays on the form with an error.
- Confirm Generate rejects a blank id and a non-numeric id, and accepts the three modes.
- PDF view and Download are checked with an existing `artifacts/*.pdf` copied into the app's artifact folder, so the viewer does not depend on a multi-minute model run.
- A full live generate is left as a manual run after the token is saved. It needs the user's PAT and several minutes of Qwen time. The plan does not paste or log the token.

## Out of scope

- Microsoft Entra sign-in. That needs an Azure app registration the repo does not have.
- Notarization, the Mac App Store, and a signed installer package.
- Pulling `qwen3.5:9b` or `phi4-mini`.
- Offline fixture mode, test-plan override, and the `score` command in the UI.
- Editing the report, writing comments back to Azure DevOps, or a multi-story portfolio PDF. Each story still gets its own PDF, which matches the current engine.
