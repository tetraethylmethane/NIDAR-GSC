/*
 * Load the ground station in a real browser and check what an operator sees.
 *
 * WHY THIS IS NOT THE SAME AS THE JEST TESTS
 * The render tests mount components under jsdom, which has no layout, no
 * network stack and no WebRTC. This drives real Chromium against the real
 * built client and the real Flask backend, so it catches the things jsdom
 * cannot: a component that throws only when the backend answers differently
 * than the fixture, a CORS refusal, a map tile 404, an element that renders
 * but is invisible or off-screen, a console error nobody would ever see.
 *
 *   node scripts/browser_check.js --client http://127.0.0.1:3000 \
 *                                 --backend http://127.0.0.1:5000
 *
 * Exits non-zero if any required rule 8.14 element is missing, so it can be a
 * pre-competition gate rather than something someone eyeballs.
 */
const fs = require("fs")
const path = require("path")
const puppeteer = require("puppeteer")

const arg = (name, dflt) => {
	const i = process.argv.indexOf(`--${name}`)
	return i > -1 ? process.argv[i + 1] : dflt
}

const CLIENT = arg("client", "http://127.0.0.1:3000")
const BACKEND = arg("backend", "http://127.0.0.1:5000")
const OUT = arg("out", path.join(__dirname, "..", "browser-check"))
const HOLD = parseInt(arg("hold", "12"), 10)

const REQUIRED = [
	// [label, regex the visible page text must match, rule 8.14 item]
	["mission progress — survivors found", /survivors/i, 8],
	["mission progress — kits delivered", /kits delivered/i, 6],
	["elapsed time", /elapsed/i, 1],
	["fleet health", /drones\s+\d+\/\d+\s+healthy/i, 7],
	["RTK status", /RTK fixed/i, 4],
	["abort control", /ABORT/, "8.19"],
	["recall control", /RECALL/, "8.19"],
	["video wall", /drone\s*1/i, 2],
]

const FORBIDDEN = [
	// Dev controls that must not exist in a mission build (rule 8.16, -50 each)
	["servo/payload control", /\bServo\b/],
	["parameter editor link", /^Params$/m],
	["write mission to aircraft", /Write To/i],
]

;(async () => {
	fs.mkdirSync(OUT, { recursive: true })
	const browser = await puppeteer.launch({
		headless: "new",
		args: [
			"--no-sandbox",
			"--disable-dev-shm-usage",
			// The mission machine has no camera or mic; make sure nothing waits
			// on a permission prompt that will never be answered.
			"--use-fake-ui-for-media-stream",
			"--window-size=1600,1000",
		],
		defaultViewport: { width: 1600, height: 1000 },
	})
	const page = await browser.newPage()

	const consoleErrors = []
	const failedRequests = []
	page.on("console", m => {
		if (m.type() === "error") consoleErrors.push(m.text())
	})
	page.on("requestfailed", r => {
		failedRequests.push(`${r.failure().errorText} ${r.url()}`)
	})
	page.on("pageerror", e => consoleErrors.push(`PAGEERROR ${e.message}`))

	const url = `${CLIENT}/?backend=${encodeURIComponent(BACKEND)}`
	console.log(`loading ${url}`)
	await page.goto(url, { waitUntil: "networkidle2", timeout: 60000 })

	// Let the fleet poll run so the displays have real data in them.
	await new Promise(r => setTimeout(r, HOLD * 1000))

	await page.screenshot({ path: path.join(OUT, "flightdata.png"), fullPage: false })
	const text = await page.evaluate(() => document.body.innerText)
	fs.writeFileSync(path.join(OUT, "page.txt"), text)

	let failures = 0
	console.log("\n=== rule 8.14 / 8.19 elements ===")
	for (const [label, re, item] of REQUIRED) {
		const ok = re.test(text)
		if (!ok) failures++
		console.log(`  ${ok ? "OK  " : "MISS"}  [${item}] ${label}`)
	}

	console.log("\n=== dev controls that must be absent (rule 8.16) ===")
	for (const [label, re] of FORBIDDEN) {
		const present = re.test(text)
		if (present) failures++
		console.log(`  ${present ? "PRESENT — FAIL" : "absent  OK"}  ${label}`)
	}

	// Map tiles: the client is hard-wired to /map/{z}/{x}/{y}.png and never
	// falls back online, so a 404 here is a blank map during the mission.
	const tile404 = failedRequests.filter(r => r.includes("/map/"))
	console.log("\n=== offline map tiles ===")
	console.log(`  failed tile requests: ${tile404.length}`)
	tile404.slice(0, 5).forEach(t => console.log(`    ${t}`))

	console.log("\n=== console errors ===")
	if (!consoleErrors.length) console.log("  none")
	consoleErrors.slice(0, 15).forEach(e => console.log(`  ${e.slice(0, 200)}`))

	console.log("\n=== other failed requests ===")
	const other = failedRequests.filter(r => !r.includes("/map/"))
	if (!other.length) console.log("  none")
	other.slice(0, 10).forEach(e => console.log(`  ${e.slice(0, 200)}`))

	fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(
		{ url, failures, consoleErrors, failedRequests }, null, 2))

	await browser.close()
	console.log(`\nscreenshot: ${path.join(OUT, "flightdata.png")}`)
	console.log(failures === 0 ? "\nBROWSER_CHECK_OK" : `\nBROWSER_CHECK_FAILED (${failures})`)
	process.exit(failures === 0 ? 0 : 1)
})().catch(e => {
	console.error("browser check crashed:", e)
	process.exit(2)
})
