# Installation, step by step

**This guide assumes you have never used a terminal.** It explains every
command before you type it, and tells you what you should see when it works.

If you are comfortable with a terminal, the [README](README.md) says the same
things in a tenth of the space. Use that instead.

---

## Read this first

This project is not one program. It is **five separate tools** that happen to
live in the same folder. You almost certainly want one of them, not all five.

Installing all five would take hours and download several gigabytes. Installing
one takes a few minutes.

### Which one do you want?

| I want to… | Install | Roughly |
|---|---|---|
| Make narrated videos from a topic, automatically | **A. Video maker** | 10 min |
| Do that, but click buttons instead of typing | **B. Video maker + window** | 12 min |
| Run the anime-series backend (the big one) | **C. Anime pipeline** | 10 min |
| See the anime pipeline in a proper web dashboard | **D. Anime pipeline + console** | 20 min |
| Turn text into speech with different voices | **E. ChatterBox Studio** | 20–40 min |

Each walkthrough is in [Part 6](#part-6-the-walkthroughs). They are independent
— you never need to do one before another, except **B needs A** and **D needs
C**.

**Everything runs on your own computer.** Nothing is uploaded anywhere unless
you specifically ask for it, and none of it costs money to run.

---

## Part 1: The absolute basics

Skip to [Part 2](#part-2-install-python) if you already know what a terminal is.

### What is a terminal?

It is a window where you type instructions instead of clicking them. When a
guide says "run this command," it means: type it into that window, then press
**Enter**.

### Opening one

**Windows** — Press the Windows key, type `powershell`, press Enter.
A dark blue window opens.

**macOS** — Press <kbd>Cmd</kbd>+<kbd>Space</kbd>, type `terminal`, press Enter.
A white or black window opens.

**Linux** — Press <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>T</kbd>.

### Using it

You will see something ending in `$` or `>` — that is the prompt, and it means
"ready." You type after it.

**Four things worth knowing:**

1. **One command per line.** Type it, press Enter, wait for the prompt to come
   back before typing the next one. If the prompt has not returned, the command
   is still working — leave it alone.

2. **Copy and paste works**, and is safer than typing. In most terminals
   <kbd>Ctrl</kbd>+<kbd>V</kbd> works; on macOS use <kbd>Cmd</kbd>+<kbd>V</kbd>;
   in some Linux terminals it is <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd>.
   If none work, right-click — many terminals paste on right-click.

3. **The terminal is always "standing in" a folder**, and commands act on that
   folder. `cd` means *change directory* — it is how you walk into a folder.
   Most problems beginners hit are just being in the wrong folder. If you get
   lost, [Part 7](#part-7-when-something-goes-wrong) shows how to check where
   you are.

4. **Do not type the `#` comments.** In this guide, anything after a `#` is a
   note to you, not part of the command.

### One convention in this guide

Where you see two versions of a command:

```bash
python3 --version      # macOS and Linux
python --version       # Windows
```

pick the line for your system. Windows spells it `python`; macOS and Linux spell
it `python3`.

---

## Part 2: Install Python

Every part of this project except the web dashboard needs Python. You need
**version 3.11 or newer**.

### Check whether you already have it

```bash
python3 --version      # macOS and Linux
python --version       # Windows
```

If it prints `Python 3.11.something` or higher — you are done, skip to
[Part 3](#part-3-install-nodejs). If it prints 3.10 or lower, or an error, carry
on.

### Windows

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Click the big yellow download button
3. Run the file you downloaded
4. **Tick the box that says "Add python.exe to PATH"** before clicking Install.
   It is at the bottom of the first screen and it is easy to miss.

That checkbox is the single most common cause of "Python is not recognized"
later. If you missed it, run the installer again and choose *Modify*.

5. Close your terminal and open a new one — it only notices new programs on
   startup — then check:

```bash
python --version
```

### macOS

macOS ships with an older Python that is not new enough. Install a current one:

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download and run the macOS installer
3. Close your terminal, open a new one, then check:

```bash
python3 --version
```

### Linux

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
python3 --version
```

(That is Debian/Ubuntu. On Fedora use `sudo dnf install python3 python3-pip`.)

---

## Part 3: Install Node.js

**Only needed for walkthrough D** (the web dashboard). Skip this otherwise.

Check first:

```bash
node --version
```

If it prints `v18` or higher, you are done. Otherwise go to
[nodejs.org](https://nodejs.org/), download the version labelled **LTS**, and
run the installer with all the default options. Then close and reopen your
terminal and check again.

---

## Part 4: Download the code

Two ways. The first needs no extra software.

### Option A — download a ZIP (simpler)

1. Open <https://github.com/Kanishka8375/youtube-pipeline>
2. Click the green **Code** button
3. Click **Download ZIP**
4. Unzip it somewhere you will remember, like your Desktop

The unzipped folder will be called `youtube-pipeline-master`. That trailing
`-master` is normal — it is the branch name.

### Option B — use git

```bash
git clone https://github.com/Kanishka8375/youtube-pipeline.git
```

This makes a folder called `youtube-pipeline`. If `git` is not installed, use
Option A.

### Now walk into the folder

This is the step people skip, and nothing works afterwards.

```bash
cd Desktop/youtube-pipeline-master     # adjust to where you actually put it
```

**A trick worth knowing:** type `cd` and a space, then drag the folder from your
file manager onto the terminal window. It fills in the path for you. Press
Enter.

Check you are in the right place:

```bash
ls          # macOS and Linux
dir         # Windows
```

You should see names like `pipeline.py`, `requirements.txt`, `anime_pipeline`.
If you do not, you are in the wrong folder — `cd` again.

---

## Part 5: Make a virtual environment

**What this is, in plain terms:** Python projects need extra parts, and
different projects want different versions of the same parts. A virtual
environment is a private box for *this* project's parts, so it cannot break
anything else on your computer. It is one folder called `.venv`, and deleting
that folder undoes everything in this step.

Do this once, from inside the project folder.

**Create it:**

```bash
python3 -m venv .venv      # macOS and Linux
python -m venv .venv       # Windows
```

Nothing is printed. That is success.

**Turn it on:**

```bash
source .venv/bin/activate      # macOS and Linux
.venv\Scripts\activate         # Windows
```

Your prompt now starts with `(.venv)`. That is how you know it is on.

> **You must turn it on again every time you open a new terminal.** It is not
> permanent. If a command suddenly says a module is missing, this is almost
> always why — check for `(.venv)` at the start of your prompt.

**Then upgrade the installer itself**, which prevents a class of confusing
errors later:

```bash
python -m pip install --upgrade pip
```

(Inside an active virtual environment, `python` is correct on every system,
including macOS and Linux.)

---

## Part 6: The walkthroughs

Each one assumes you have done Parts 4 and 5, your terminal is in the project
folder, and your prompt shows `(.venv)`.

---

### A. Video maker

Give it a topic, get back a narrated video with images and music.

**Install the parts:**

```bash
pip install -r requirements.txt
```

This prints many lines and takes a few minutes. Lines beginning `Collecting`
and `Installing` are normal progress. It has worked when the prompt comes back
and you see `Successfully installed …`.

**Give it a brain.** The tool writes the script using an AI model, and you must
pick one. All three are free.

*Option 1 — Groq (easiest; a website, no big download)*

1. Sign up at [groq.com](https://groq.com) and create an API key
2. Make your settings file:

```bash
cp .env.example .env       # macOS and Linux
copy .env.example .env     # Windows
```

3. Open `.env` in any text editor (Notepad is fine) and put your key on the
   `GROQ_API_KEY=` line, replacing the placeholder text. Save.

*Option 2 — Ollama (runs on your computer, no key, no limits, ~2 GB download)*

Install from [ollama.com](https://ollama.com), then in a **second** terminal:

```bash
ollama pull llama3.2
ollama serve
```

Leave that second terminal running — closing it turns the brain off.

*Option 3 — Google Gemini* — same as Groq, but get the key from
[Google AI Studio](https://aistudio.google.com) and put it on the
`GEMINI_API_KEY=` line.

**Make a video:**

```bash
python pipeline.py --topic "How solar panels work" --duration 60
```

`--duration` is in seconds. You can leave `--topic` off entirely and it will ask
you for one.

The finished video appears in the `output/` folder.

> **Nothing is uploaded to YouTube.** Uploading only happens if you add
> `--upload`, which needs Google credentials you have not set up. Without that
> flag the tool never contacts YouTube at all. And if you do set it up later,
> uploads default to *private*.

---

### B. Video maker, in a window

A clickable interface instead of typed commands. **Do walkthrough A first.**

```bash
pip install flask flask-cors
python web_ui.py
```

Then open <http://localhost:5000> in your browser.

> **Why the extra install line?** This is a known gap in the project, not a
> mistake on your part: `web_ui.py` needs Flask, but Flask is missing from the
> requirements list, so installing walkthrough A does not bring it in. The line
> above fills the gap. Without it you get
> `ModuleNotFoundError: No module named 'flask'`.

**Prefer a real desktop window** rather than a browser tab:

```bash
cd desktop_app
pip install pywebview
python launcher.py
```

To get back to the main folder afterwards: `cd ..` (two dots means "up one").

---

### C. Anime pipeline

The largest component: a server for running a serialized anime channel, with
thirteen specialist agents and a continuity system that stops the story
contradicting itself.

**This needs no API keys and no database.** It ships with a built-in fake AI
provider so the whole thing runs end to end with nothing configured. Good for
seeing what it does before committing to anything.

**Walk into its folder and install:**

```bash
cd anime_pipeline
pip install -e ".[dev]"
```

The quotes matter — without them some terminals mis-read the square brackets.

**Build its database:**

```bash
alembic upgrade head
```

You will see a wall of `INFO ... running upgrade` lines. That is it creating 36
tables in a file on your disk. No database software required.

**Start it:**

```bash
uvicorn app.main:app --reload
```

This one **does not give the prompt back** — it is a server, it stays running.
That is correct. To stop it, press <kbd>Ctrl</kbd>+<kbd>C</kbd>.

**Look at it:** open <http://127.0.0.1:8000/docs>

That page lists everything the server can do, and each entry has a **Try it
out** button that runs it right there in the browser. You do not need to type
commands to explore it.

**Make yourself an account** using that page:

1. Find `POST /auth/register` and click it
2. Click **Try it out**
3. Replace the example text with your details:

```json
{"email": "you@example.com", "password": "a-long-passphrase", "full_name": "Your Name"}
```

4. Click **Execute**

A response code of `200` or `201` means it worked. If you get `422`, check the
spelling of `full_name` — the server deliberately rejects unknown field names
rather than silently ignoring them, so a typo is reported instead of losing your
data.

---

### D. Anime pipeline with the web dashboard

A proper operations interface: dashboard, pipeline diagram, job queue, live
provider status. **Do walkthrough C first**, and you need Node.js from
[Part 3](#part-3-install-nodejs).

You will need **two terminals open at once**. This is normal — one runs the
server, one runs the dashboard.

**Terminal 1 — the server.** From the project folder:

```bash
cd anime_pipeline
```

macOS and Linux:

```bash
ANIME_CORS_ORIGINS="http://localhost:3001,http://127.0.0.1:3001" uvicorn app.main:app --reload
```

Windows PowerShell (it sets variables differently — two lines):

```powershell
$env:ANIME_CORS_ORIGINS="http://localhost:3001,http://127.0.0.1:3001"
uvicorn app.main:app --reload
```

That long setting gives the dashboard permission to talk to the server. Browsers
block this by default, and both spellings are listed because `localhost` and
`127.0.0.1` count as different places to a browser even though they are the same
computer.

Leave this terminal running.

**Terminal 2 — the dashboard.** Open a new terminal, go to the project folder
again ([Part 4](#part-4-download-the-code)), then:

```bash
cd frontend
npm install
```

`npm install` prints a lot and can take a few minutes. Warnings about
"deprecated" packages are normal and safe to ignore.

```bash
cp .env.example .env.local      # macOS and Linux
copy .env.example .env.local    # Windows

npm run build
npm run start
```

Open <http://localhost:3001> and sign in with the account you made in
walkthrough C.

> **If you ever change the address of the server**, edit `.env.local` and then
> run `npm run build` **again**. That address is baked in during the build —
> restarting alone will not pick up the change, and the dashboard will keep
> using the old one with no error to explain why.

---

### E. ChatterBox Studio

A web app for turning text into speech with several different voice models.

```bash
pip install -r requirements-chatterbox.txt
```

> **This is the longest install in the project** — it downloads PyTorch, which
> is well over a gigabyte. Expect ten minutes or considerably more on a slow
> connection. It is not stuck; leave it be.

```bash
python chatterbox_app.py
```

Open <http://localhost:5001>.

To add voice models later, put them in
`chatterbox_studio/models/tts/<model-name>/` and click **⟳ Refresh Models** in
the app. No restart needed.

---

## Part 7: When something goes wrong

Find the message you actually saw. The exact words matter more than they look
like they do.

### "python is not recognized" / "command not found: python3"

Your computer does not know where Python is.

- **Windows:** the "Add python.exe to PATH" box was not ticked. Re-run the
  installer and choose *Modify*, or reinstall with the box ticked
  ([Part 2](#part-2-install-python)).
- **Windows, and it opened the Microsoft Store instead:** you typed `python3`.
  On Windows the command is `python`.
- **Any system:** you did not close and reopen the terminal after installing.
  Do that — terminals only notice new programs when they start.

### "No module named …"

Something is not installed, or you are not in the box.

1. Look at your prompt. Does it start with `(.venv)`? If not, turn the virtual
   environment on again ([Part 5](#part-5-make-a-virtual-environment)) — this is
   the cause the vast majority of the time.
2. If it does, you have not run the `pip install` line for that walkthrough.
3. If the missing module is specifically `flask`, that is the known gap in
   walkthrough B — `pip install flask flask-cors`.

### "No such file or directory" / "cannot find the path"

You are standing in the wrong folder. Check where you are:

```bash
pwd         # works in PowerShell, macOS and Linux alike
```

Then list what is there (`ls`, or `dir` on Windows) and compare against what the
step expects. `cd ..` goes up one level; `cd foldername` goes down into one.

### PowerShell: "running scripts is disabled on this system"

Windows blocks the activation script by default. Allow it for this window only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then run the activate line again. `-Scope Process` means it applies to this
terminal window and nothing else, and it resets when you close it.

### The command seems frozen

Some are genuinely slow — `pip install`, `npm install`, and anything downloading
PyTorch. Give them several minutes before worrying.

But `uvicorn`, `npm run start`, `ollama serve`, `python web_ui.py` and
`python chatterbox_app.py` are **servers**: they are supposed to keep running
and never give the prompt back. That is not frozen, that is working. Press
<kbd>Ctrl</kbd>+<kbd>C</kbd> to stop one.

### The page will not load in my browser

- Is the terminal that started it still open and running? Closing that terminal
  stops the server.
- Check the address, including the port number after the colon: the video maker
  UI is `:5000`, ChatterBox is `:5001`, the dashboard is `:3001`, the anime
  server is `:8000`.
- Use `http://`, not `https://`. These run locally without certificates.

### The dashboard loads but shows errors about CORS

The server was started without the `ANIME_CORS_ORIGINS` line from walkthrough D,
or with only one of the two spellings. Stop it with <kbd>Ctrl</kbd>+<kbd>C</kbd>
and start it again with the full line.

### "Address already in use"

Something is already running on that port — usually the same program in another
terminal you forgot about. Close the other terminal, or start this one on a
different port (`--port 5002` for ChatterBox, `uvicorn … --port 8001` for the
anime server).

### "InsecureSecretError" when starting the anime server

You have set `ANIME_ENV` to a production value while the signing key is still
the shipped default. The server refuses to start rather than run insecurely.
Either unset `ANIME_ENV`, or set a real key — see §3.4 of the
[README](README.md#34-configuration).

### Ollama: "connection refused"

`ollama serve` is not running. It needs its own terminal, left open.

### Still stuck

Open an [issue](https://github.com/Kanishka8375/youtube-pipeline/issues) with
the command you ran and the **last twenty lines** of what it printed. The error
text is what makes a problem diagnosable; "it did not work" is not enough to go
on.

---

## Glossary

| Word | What it means |
|---|---|
| **terminal** / shell / command line | The window where you type commands |
| **command** | One line you type, then press Enter |
| **prompt** | The `$` or `>` where you type; when it comes back, the last command has finished |
| **directory** | A folder |
| `cd` | "Change directory" — walk into a folder. `cd ..` walks back out |
| `ls` / `dir` | List what is in the current folder |
| **PATH** | The list of places your computer looks for programs. If something is "not on PATH", the computer cannot find it even though it is installed |
| **package** | A reusable piece of code someone else wrote |
| `pip` | Installs Python packages |
| `npm` | Installs JavaScript packages |
| **virtual environment** (venv) | A private box holding one project's packages, so projects cannot break each other |
| **server** | A program that keeps running and answers requests. Stays open; does not return the prompt |
| **port** | The number after the colon in an address, like `:8000`. Different programs on one computer use different ports |
| **API key** | A password that identifies you to an online service. Keep it secret |
| **repository** / repo | The project folder, and its history |
| **CORS** | A browser rule about which sites may talk to which servers. Why the dashboard needs to be granted permission |

---

## What next

- [README](README.md) — the same instructions, condensed, plus every
  configuration option
- [Channel Operating Kit](docs/channel-operating-kit/README.md) — the
  non-technical half: weekly checklists, scheduling, thumbnail testing
- [Anime pipeline design docs](docs/anime-pipeline/) — how the continuity
  system actually works
