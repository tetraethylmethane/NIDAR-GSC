# Drikr NIDAR Ground Station

Mission ground station for **NIDAR 2026–27, Track 1, Mission 1 — RescueSwarm**:
three autonomous drones searching a flood zone, geotagging survivors and
delivering medical kits, on one unified operator interface with no external
network.

- **Systems engineering, requirements and sizing:** [Drikr-NIDAR](https://github.com/tetraethylmethane/NIDAR-RescueSwarm)
- **What must not be changed back:** [`MISSION.md`](MISSION.md)

```bash
cd server && MISSION_MODE=1 python -m pytest mission_tests -q   # 86 tests
./scripts/check-no-network.sh                                   # rule 8.4 guard
python scripts/sim_mission.py --speed 8                         # 3 drones, no aircraft
```

## What it does

| Rule 8.14 requires | Where |
|---|---|
| Mission status | `MissionStatus.js` |
| Live camera feed from **each** drone | `VideoWall.js` + MediaMTX |
| Position of each drone | `MissionLayers.js` |
| Assigned search area per drone | `MissionLayers.js` — colour-coded, the visible proof for 4D-3 |
| Geotagged survivor locations | `MissionLayers.js` — coloured by GNSS fix quality |
| Kit delivery status | `MissionLayers.js` + `MissionStatus.js` |
| Comms and system health | `MissionStatus.js` |
| Consolidated mission progress | `MissionStatus.js` |

**Mission builds expose no vehicle commands.** Abort and recall only — see
[`MISSION.md`](MISSION.md) §2 and §5.

> ⚠ **The abort button is not yet connected to anything.** `/api/safety/abort`
> sets a flag that nothing reads. Until the 868 MHz chain is built it must be
> labelled NOT IMPLEMENTED in the UI. See the systems repo,
> `docs/implementation-plan.md` §4.

## Provenance

Forked from Team Sammpaati's ground station, which was written for **AUVSI SUAS**
— a different competition with different rules. That lineage caused real
problems, all now fixed and recorded in [`MISSION.md`](MISSION.md): an internet
poller that breached rule 8.4, a single-vehicle data model against a
three-aircraft mission, and a full command surface in what had to be a
mission-safe build. AUVSI-specific features (interop submissions, ODLC service,
UGV) have been removed.

---

## Set Up Server

The backend/server for the ground station is written in Python Flask as an API for the frontend to communicate with.
To set up the server, first enter the `server` directory:
```bash
cd server
```

### Finding the right Python to use
To correctly set up the server, you will need to use the right version of Python.
Currently, the server is only compatible with Python 3.9+.
To use Python 3.10+, you will need to edit some source code in the `venv` module.

First, download a Python 3.9+ version from [python.org](https://www.python.org/downloads/).
To find the right version of Python to use, run the following command:
```bash
python --version
```

Repeat this command with `python3`, `python3.x`, and `py` until you find the right command to use for your system.
Use this version of Python for the rest of the setup.


### The Virtual Environment

#### Create it

To create a venv, run
```bash
python -m venv venv
```

#### Activate it

This will need to be done each time you run the server.

For Linux and MacOS, run:
```bash
source venv/bin/activate
```
and for Windows, run:
```bash
.\venv\Scripts\activate
```

*Note: Once the venv is activated, the `python` command will refer to the version of Python within the venv.
Therefore, you should not use the version of Python you determined earlier, and instead use `python` for the rest of the
setup.*

Tip: If you ever need to exit the virtual environment, run
```bash
deactivate
```

##### Install required packages

install necessary packages into the venv by running
```bash
python -m pip install -r requirements.txt
```

Even if you are running Archlinux (or its derivatives), you'll still want to use pip rather than pacman for this as the 
packages installed with pip while in the venv will save to the venv rather than for the user or globally.

### Configuration

#### Set up configuration

On Linux/MacOS, run:
```bash
cp sample.config.json config.json
```
and for Windows, run:
```bash
copy sample.config.json config.json
```

This file is used for configuration of the backend. 
For now, the default options in sample.config.json should be enough to set up the server.

#### Create logs folder

There's a chance that the `logs` folder is not present when cloning with Git. 
If the folder exists in the `server` directory, you can ignore this step.
If the folder does not exist, make a new empty folder called `logs`.

#### Fix dronekit module

If your version of Python (`python --version`) is Python 3.10 or higher, you'll need to edit some module source code.

1) Open the `venv` directory
2) Open the `lib` directory
3) Open the `python3.x` directory
4) Open the `site-packages` directory
5) Open the `dronekit` directory (if this does not exist, make sure you installed the required packages correctly)
6) Open the `__init__.py` in a text editor
7) Search in the file for the `class Parameters` class definition. Only one result should show up (possibly line 2689)
8) Change that line from `class Parameters(collections.MutableMapping, HasObservers):` to 
`class Parameters(collections.abc.MutableMapping, HasObservers):`

### Running the Server

Open a new terminal and run 
```bash
python app.py
```

If you make any edits, you will need to end the program and restart the backend.

## Client

The frontend/client for the ground station is written in React, along with some other libraries.
The backend (and by extension the Interop server) must be running before the frontend can run. Starting the client 
without the backend running may result in an error, or silent failure.

### Installing Client Packages

*Note: if npm does not work, you may have to install Node.js. To do so, use this link: 
https://nodejs.org/en/download/ or download it from your distribution's package manager.*

Run `npm i` in `client/`.
This installs all of the necessary packages (specified in package.json and package-lock.json).<br />

### Starting the Client

Run `npm run start` or `npm start` in `client/`.
This will open the client in your browser. If not, note that it is run on 
[http://localhost:3000](http://localhost:3000); you can load that in your web browser to connect to the client.

The page will reload if you make edits to the source.
You will also see any linter errors in the console.

## Version Control

Create and check out a new git branch, branched from the `dev` branch, before beginning to work on a new change. When an 
entire feature is complete (don't open a PR for something that isn't done, unreviewed, or untested, unless it is a draft 
PR), push the branch to your fork, then open a PR to the `dev` branch; PR's should generally target `dev`. Describe what 
changes are made, how they are implemented, other notes, and add Team Sammpaati programmers such as 
[@William](https://github.com/pizzalemon) or [@Krishnan](https://github.com/KrishnanS2006) to review it.

Commit messages should be helpful, and not silly. As a rule of thumb, programmers with knowledge of how the entire 
Ground Station works should know what your commit does just by the message. Do not commit something that is incomplete, 
unreviewed, or untested. Commits should represent a working self-contained block of your work.
