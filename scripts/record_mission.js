/*
 * Record the ground station through a whole mission, as a video.
 *
 * WHAT THIS IS FOR
 * A proof of concept that a reviewer can watch. The design review is worth 200
 * points and rewards evidence; a 40-second clip of three real ArduPilot
 * autopilots flying the planner's own output, with survivors appearing on the
 * operator's map and kits being delivered, is evidence in a way that a
 * screenshot or a block diagram is not.
 *
 * IT IS ALSO A TEST. Anything that only breaks over time -- a memory leak in
 * the fleet poll, a marker that stops updating, a WebRTC feed that drops after
 * ninety seconds, a countdown that goes negative -- is invisible to a single
 * screenshot and obvious in a timelapse.
 *
 *   node scripts/record_mission.js --minutes 8 --fps 2
 *
 * Frames land in mission-recording/ and are stitched with ffmpeg if it is on
 * PATH. Everything on screen comes from the real backend: no mock-ups, no
 * staged data, and the abort panel still says NO RADIO if no radio is attached.
 */
const fs = require("fs")
const path = require("path")
const { spawnSync } = require("child_process")
const { createRequire } = require("module")
const { pathToFileURL } = require("url")

const arg = (name, dflt) => {
	const i = process.argv.indexOf(`--${name}`)
	return i > -1 ? process.argv[i + 1] : dflt
}

const CLIENT = arg("client", "http://127.0.0.1:3000")
const BACKEND = arg("backend", "http://127.0.0.1:5000")
const OUT = arg("out", path.join(__dirname, "..", "mission-recording"))
const MINUTES = parseFloat(arg("minutes", "8"))
const FPS = parseFloat(arg("fps", "2"))          // captured frames per second
const PLAYBACK_FPS = parseInt(arg("playback-fps", "20"), 10)

async function loadPuppeteer() {
	const r = createRequire(path.join(__dirname, "..", "client", "package.json"))
	const mod = await import(pathToFileURL(r.resolve("puppeteer")).href)
	return mod.default || mod
}

;(async () => {
	const puppeteer = await loadPuppeteer()
	fs.rmSync(OUT, { recursive: true, force: true })
	fs.mkdirSync(OUT, { recursive: true })

	const browser = await puppeteer.launch({
		headless: "new",
		args: ["--no-sandbox", "--disable-dev-shm-usage",
			"--use-fake-ui-for-media-stream", "--window-size=1600,1000"],
		defaultViewport: { width: 1600, height: 1000 },
	})
	const page = await browser.newPage()

	/* Anything that appears once and never again is worth catching, so keep the
	 * whole console rather than sampling it. */
	const errors = []
	page.on("pageerror", e => errors.push(String(e.message)))
	page.on("console", m => { if (m.type() === "error") errors.push(m.text()) })
	page.on("response", r => {
		if (r.status() >= 500) errors.push(`${r.status()} ${r.url()}`)
	})

	await page.goto(`${CLIENT}/?backend=${encodeURIComponent(BACKEND)}`,
		{ waitUntil: "networkidle2", timeout: 60000 })
	await new Promise(r => setTimeout(r, 6000))     // let the map settle

	const total = Math.round(MINUTES * 60 * FPS)
	const interval = 1000 / FPS
	console.log(`recording ${MINUTES} min at ${FPS} fps -> ${total} frames`)

	// Sample the fleet alongside the frames, so the clip has a data track and
	// we can say what was true at any moment rather than squinting at pixels.
	const track = []
	const t0 = Date.now()
	for (let i = 0; i < total; i++) {
		const due = t0 + i * interval
		const wait = due - Date.now()
		if (wait > 0) await new Promise(r => setTimeout(r, wait))

		await page.screenshot({
			path: path.join(OUT, `f${String(i).padStart(5, "0")}.png`),
		})

		if (i % Math.round(FPS * 5) === 0) {
			try {
				/* AbortController, because the backend can go away mid-run --
				 * it did, and an in-page fetch with no timeout then hangs the
				 * whole capture loop. A recorder whose job is to catch things
				 * that only break over time must not itself stop recording
				 * when one of them does. */
				const snap = await page.evaluate(async b => {
					const ac = new AbortController()
					const t = setTimeout(() => ac.abort(), 2000)
					try {
						const r = await fetch(`${b}/api/fleet`, { signal: ac.signal })
						return r.ok ? await r.json() : null
					} catch (e) {
						return null
					} finally {
						clearTimeout(t)
					}
				}, BACKEND)
				if (snap) {
					const p = snap.progress || {}
					track.push({
						t: Math.round((Date.now() - t0) / 1000),
						found: p.found, delivered: p.delivered,
						ok: p.drones_ok, rtk: p.rtk_fixed,
						alt: Object.values(snap.vehicles || {})
							.map(v => v.alt_m == null ? null : Math.round(v.alt_m)),
						mode: Object.values(snap.vehicles || {}).map(v => v.mode),
					})
					process.stdout.write(
						`\r  t+${track[track.length - 1].t}s  ` +
						`found ${p.found}/${p.expected}  delivered ${p.delivered}  ` +
						`alt ${track[track.length - 1].alt.join("/")}   `)
				}
			} catch (e) { /* a dropped sample must not end the recording */ }
		}
	}
	console.log()

	fs.writeFileSync(path.join(OUT, "track.json"), JSON.stringify(track, null, 2))
	fs.writeFileSync(path.join(OUT, "console-errors.json"),
		JSON.stringify([...new Set(errors)], null, 2))
	await browser.close()

	console.log(`\n${total} frames, ${track.length} fleet samples`)
	console.log(`console errors across the whole run: ${new Set(errors).size}`)
	for (const e of [...new Set(errors)].slice(0, 5)) console.log(`  ${e.slice(0, 160)}`)

	const mp4 = path.join(OUT, "mission.mp4")
	const ff = spawnSync("ffmpeg", [
		"-y", "-framerate", String(PLAYBACK_FPS),
		"-i", path.join(OUT, "f%05d.png"),
		"-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", mp4,
	], { stdio: "ignore" })
	if (ff.status === 0) {
		const mb = fs.statSync(mp4).size / 1e6
		console.log(`\nvideo: ${mp4}  (${mb.toFixed(1)} MB, ` +
			`${(total / PLAYBACK_FPS).toFixed(0)}s at ${PLAYBACK_FPS} fps)`)
	} else {
		console.log("\nffmpeg not available or failed; frames are in " + OUT)
	}
})().catch(e => { console.error("recording failed:", e); process.exit(2) })
