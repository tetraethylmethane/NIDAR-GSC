import axios from "axios"

/*
 * Where the ground-station backend lives.
 *
 * This used to be hardcoded to http://172.29.93.93:5000 -- a machine on the
 * previous team's network. Nothing in the repo could talk to a backend on any
 * other host without editing source and rebuilding, which is why the client and
 * server had never been run together.
 *
 * Resolution order, first match wins:
 *
 *   1. ?backend=http://host:5000     query string, for a one-off
 *   2. localStorage nidar_backend    sticky, survives reload
 *   3. REACT_APP_BACKEND             baked in at build time
 *   4. the host serving this page, port 5000
 *
 * (4) is the one that matters operationally: the mission laptop serves the
 * client and runs the backend, so "same host, port 5000" is correct without
 * anyone configuring anything. It is also the safe default under rule 8.4 --
 * it can only ever point at wherever the page itself came from, so it cannot
 * become an outbound internet call by accident.
 */
const DEFAULT_PORT = 5000

const resolveUrl = () => {
	if (typeof window === "undefined") return `http://127.0.0.1:${DEFAULT_PORT}`

	const q = new URLSearchParams(window.location.search).get("backend")
	if (q) return q.replace(/\/+$/, "")

	try {
		const stored = window.localStorage.getItem("nidar_backend")
		if (stored) return stored.replace(/\/+$/, "")
	} catch (e) {
		/* localStorage can throw in a sandboxed iframe; fall through. */
	}

	if (process.env.REACT_APP_BACKEND) {
		return process.env.REACT_APP_BACKEND.replace(/\/+$/, "")
	}

	const host = window.location.hostname || "127.0.0.1"
	return `http://${host}:${DEFAULT_PORT}`
}

var url = resolveUrl()

const httpget = async (endpoint, func, error) => {
    try {
        const response = await axios.get(url + endpoint, {
            headers: { "Content-Type": "application/json", Accept: "application/json" },
        })
        if (func) func(response)
        return response
    } catch (e) {
        if(error) {
            error(e)
        }
        if (e.response) {
            return {"error": e.response.status}
        }
    }
}

const httppost = async (endpoint, data, func) => {
    const response = await axios.post(url + endpoint, data)
    if (func) func(response)
    return response
}

const getUrl = () => {
    return url
}

const setUrl = (u) => {
    url = u.replace(/\/+$/, "")
    /* Remember it. Retyping the backend address after every reload during a
     * 5-minute setup window is exactly the sort of friction that produces a
     * mistake. */
    try {
        window.localStorage.setItem("nidar_backend", url)
    } catch (e) {
        /* not fatal */
    }
}

export { httpget, httppost, getUrl, setUrl }
