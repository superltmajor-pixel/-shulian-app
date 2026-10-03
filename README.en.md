# Shulian (数恋)

[简体中文](README.md) | **English**

Shulian is a local-first digital companion desktop app for Windows. It combines a FastAPI backend, a React frontend, and a pywebview desktop shell in a standalone client, with character companionship, streaming chat, relationship memory, speech synthesis, and local character profiles.

Character content is stored separately from the application code. A fresh installation includes no characters; create or import them on the app's “Lovers” page.
Personal characters, personas, images, and conversations are not distributed with the source code or update packages. See [Local Characters and Public Source Code](docs/local-character-data.md) (Chinese).

## Features

- Create, edit, import, and manage local characters in the app
- Configure AI services, stream conversations, and retain context across chats
- Track intimacy, relationship agreements, conversation history, and character profiles
- Generate speech with Edge TTS and GPT-SoVITS
- Choose dark, light, or system themes
- Use a native Windows desktop window with persistent local data
- Store API keys with encryption, separately from source code and installation packages
- Enable performance mode to reduce glass blur and pause ambient animations while the window is in the background

## Technology stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.14, FastAPI, Uvicorn, Pydantic |
| AI | OpenAI Python SDK, DeepSeek API |
| Frontend | React 18, JSX/CSS, local Vite builds |
| Desktop | pywebview, Microsoft Edge WebView2 |
| Speech | edge-tts, GPT-SoVITS |
| Packaging | PyInstaller onedir |
| Testing | Python `unittest` |

## Project structure

```text
shulian-backend/
├─ main.py                     # FastAPI app, API routes, and static resource entry point
├─ desktop.py                  # Desktop window, backend startup, and single-instance control
├─ chat.py                     # AI conversations and prompt assembly
├─ characters.py               # Shared character models
├─ role_content.py             # Loads local character-specific configuration
├─ status_engine.py            # Character state and schedules
├─ ai_credentials.py           # API key validation and encrypted local storage
├─ role_archive.py             # Character profiles and snapshots
├─ web/                        # Shared React frontend and styles
├─ tests/                      # Automated regression tests
├─ docs/                       # Additional project documentation
├─ requirements.txt            # Backend runtime dependencies
├─ .env.example                # Example of non-sensitive runtime configuration
├─ shulian-onedir.spec         # PyInstaller configuration for the production desktop client
├─ package-shulian-inplace.ps1 # Updates the production client in place
└─ start.bat                   # Starts browser development mode
```

`build/`, `dist/`, `venv/`, logs, user media, and the local `.env` file are generated files or local state and should not be committed to the repository.

## Quick start

### 1. Prepare your environment

Windows 10/11 and Python 3.14 are recommended. The current frontend build supports Node.js 20.19.x and newer 20.x versions, or Node.js 22.12 and later, and requires npm.

Vite builds the frontend into a local bundle, so it does not depend on a CDN at runtime. After changing the frontend, run `npm ci`, `npm run build:web`, and `npm run check:web`.

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

For desktop development and packaging, also install:

```powershell
.\venv\Scripts\python.exe -m pip install pywebview pyinstaller pythonnet
```

### 2. Configure runtime settings

Copy `.env.example` to `.env` and adjust the model, timeout, and TTS settings as needed.

```powershell
Copy-Item .env.example .env
```

Do not put API keys in `.env`. On the first client launch, configure your key in the AI connection screen. Once validation succeeds, the client stores it locally using Windows Data Protection API (DPAPI) encryption.

### 3. Start the development environment

Browser development mode:

```powershell
.\start.bat
```

- App: <http://127.0.0.1:8000/>
- API documentation: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/health>

Desktop development mode:

```powershell
.\venv\Scripts\python.exe .\desktop.py
```

The desktop client uses the fixed address `127.0.0.1:8770` and checks for an existing instance and port conflicts.

## Testing

Run the complete offline regression suite. It automatically isolates character, chat-state, and credential paths and blocks connections to external services:

```powershell
.\venv\Scripts\python.exe scripts/check-quality.py --verbose
```

Check the syntax of the main Python files:

```powershell
.\venv\Scripts\python.exe -m py_compile main.py chat.py desktop.py
```

The number of tests grows as features are added; use the actual command output as the record of what ran. Do not treat a run that skips failures or directly accesses personal runtime data as successful validation.

## Packaging and releases

For download instructions and data-preservation steps for end users, see [Public Test Release Updates](docs/public-updates.md) (Chinese). The first public package is still being prepared. The current update entry point does not automatically check for, download, or install new versions from GitHub.

Configure the packaging paths, then run the script from the source directory. The paths below are examples; replace them with your own source and client directories:

```powershell
$env:SHULIAN_REPO = (Get-Location).Path
$env:SHULIAN_APP_DIR = 'C:\Apps\Shulian\dist'
pwsh -NoProfile -File .\package-shulian-inplace.ps1
```

Alternatively, create a local `packager.local.json` beside the script and set `repo` and `appDir` to absolute paths. This file is ignored by Git. The script uses `shulian-onedir.spec`, runs offline checks and a frontend build, creates release artifacts, and updates the specified client in place. It may close and restart the app. Run it only when you are ready to perform an actual client update.

Confirm each release stage separately:

1. `code modified`: The source code has been changed.
2. `resources synced`: Frontend resources and packaging scripts have been synchronized.
3. `EXE packaged`: The production EXE has been rebuilt.
4. `client verified`: The client in the installation directory has actually been launched and verified.

Passing source-level tests does not establish that the production client has been updated.

## Data and configuration

The production client's data is organized as follows:

| Path | Contents | Handling during a client update |
| --- | --- | --- |
| `%LOCALAPPDATA%\Shulian\role-library` | Local character profiles and resources | Must be preserved |
| `%LOCALAPPDATA%\Shulian\data\shulian.sqlite3` | Main store for chats, relationships, and application state | Must be preserved |
| `dist\webview-data` | Local Storage, login state, and WebView cache | Must be preserved |
| `dist\media` | User voice recordings and media files | Must be preserved |
| `dist\.env` | Non-sensitive settings such as models, timeouts, and TTS | Must be preserved |
| `dist\_internal` | Python runtime and read-only frontend resources | May be replaced by a new package |
| `dist\Shulian.exe` | Desktop application entry point | May be replaced by a new package |

The client's credentials module manages API keys with encryption. Never hardcode keys, commit them to the repository, or include them in `_internal\.env`.
These are the default locations; environment variables such as `SHULIAN_ROLE_LIBRARY_DIR` and `SHULIAN_STATE_DB` can override the corresponding paths.

## Diagnostics

After starting the production client, check:

```text
http://127.0.0.1:8770/health
http://127.0.0.1:8770/api/self-check
```

By default, the packaged client writes `shulian-debug.log` beside `Shulian.exe`; source mode writes it in the source directory. Set `SHULIAN_LOG_DIR` to override the log directory.

Common issues:

- **Port `8770` is in use:** Close the old Shulian process or the program using that port, then try again.
- **The window opens but the page does not render:** Run the frontend build checks and confirm that the local bundle exists and matches the source.
- **The frontend still shows an old page:** Check that the cache version, copies of the packaging script, and resources in the production package are consistent.
- **Data is missing after an update:** Stop overwriting files immediately and check whether `webview-data`, `media`, or `.env` was accidentally deleted.
- **TTS does not work:** Check `TTS_PROVIDER` and the GPT-SoVITS service address in `.env`.

## Current version

- Version and build identifier: See `release.json`. Verify the source and the installed client separately.
- Desktop port: `8770`
- Development port: `8000`
- Bundled characters: 0. All characters come from local profiles.

## Contributing and version management

- Include or update the relevant tests when changing functionality.
- When frontend resources change, update the cache version in `web/index.html` as well.
- Do not commit `.env`, API keys, user media, WebView data, or build directories.
- Preserve unrelated workspace changes. Do not use destructive Git commands to remove other people's work.
- Before a production release, record the build identifier, test results, package size, data-preservation checks, and rollback location.

## License

Source code and accompanying documentation owned by this project, or which the project is authorized to release under this license, are licensed under the **GNU Affero General Public License v3.0 only (AGPL-3.0-only)**. See [LICENSE](LICENSE) for the full terms and [LICENSING.md](LICENSING.md) for the scope of the license.

The AGPL permits commercial use, charging fees, and redistribution, subject to its requirements for corresponding source, license notices, and applicable network interactions. If you need permission for uses outside the AGPL, such as integration into closed-source software, separate terms may be negotiated as described in [Commercial Licensing](COMMERCIAL_LICENSE.md) (Chinese). Commercial use itself does not require purchasing an additional license.

Using this software does not grant an open-source license to personal characters, personas, images, audio, chat history, or local configuration, and these are not distributed with the source code. Third-party components remain subject to their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

- Brand and name usage: [TRADEMARKS.md](TRADEMARKS.md).
- Contributions: [CONTRIBUTING.md](CONTRIBUTING.md). Code and documentation contributors must complete the contribution authorization described in [CLA.md](CLA.md) before their contributions are merged.
